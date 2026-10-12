import sys
import time
from pathlib import Path

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .exporter import export_game
from .google import MAX_BATCH, google_language, translate_google
from .model import LANGUAGE, Entry, Project, export_csv, import_csv
from .pipeline import create_project
from .sdk import find_sdk, sdk_launcher


class ExtractionWorker(QThread):
    progress = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        executable: Path,
        destination: Path,
        language: str,
        parent=None,
        *,
        sdk_path: Path | None = None,
        include_yaml: bool = False,
    ):
        super().__init__(parent)
        self.executable = executable
        self.destination = destination
        self.language = language
        self.last_progress = 0.0
        self.sdk_path = sdk_path
        self.include_yaml = include_yaml

    def report(self, text: str):
        now = time.monotonic()
        if now - self.last_progress >= 0.05:
            self.last_progress = now
            self.progress.emit(text)

    def run(self):
        try:
            project = create_project(
                self.executable,
                self.destination,
                self.language,
                self.report,
                sdk_path=self.sdk_path,
                include_yaml=self.include_yaml,
            )
            self.succeeded.emit(project)
        except Exception as exc:
            self.failed.emit(str(exc))


class GoogleWorker(QThread):
    translated = Signal(str, str)
    progress = Signal(int, int)
    failed = Signal(str)
    completed = Signal(int, int)

    def __init__(self, entries: list[Entry], target: str, parent=None):
        super().__init__(parent)
        if not 1 <= len(entries) <= MAX_BATCH:
            raise ValueError("Selecione de 1 a 25 textos para traduzir.")
        self.items = [(entry.id, entry.source) for entry in entries]
        self.target = target

    def run(self):
        success = 0
        errors = 0
        for index, (identifier, source) in enumerate(self.items, 1):
            if self.isInterruptionRequested():
                break
            self.progress.emit(index, len(self.items))
            try:
                translated = translate_google(source, self.target)
                self.translated.emit(identifier, translated)
                success += 1
            except Exception as error:
                errors += 1
                self.failed.emit(f"Texto {index}: {error}")
                # Don't send the rest of the queue after a service/network failure.
                break
            if index < len(self.items):
                self.msleep(400)
        self.completed.emit(success, errors)


class EntryModel(QAbstractTableModel):
    headers = ["Google", "Estado", "Tipo", "Original", "Tradução", "Arquivo / linha"]
    marks_changed = Signal()
    limit_reached = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries: list[Entry] = []
        self.marked_ids: set[str] = set()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self.entries[index.row()]
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            return Qt.CheckState.Checked if entry.id in self.marked_ids else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            return [
                "",
                entry.status,
                entry.kind,
                entry.source.replace("\n", " ↵ "),
                entry.translation.replace("\n", " ↵ "),
                f"{entry.file}:{entry.line}",
            ][index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{entry.file}:{entry.line}\n{entry.context}\n{entry.source}"
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 1:
            return QColor(
                {
                    "Pendente": "#9caec3",
                    "Traduzido": "#73bdff",
                    "Revisado": "#67dfb4",
                    "Verificar tags": "#ffbd72",
                }[entry.status]
            )
        return None

    def flags(self, index):
        flags = super().flags(index)
        return flags | Qt.ItemFlag.ItemIsUserCheckable if index.column() == 0 else flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.CheckStateRole or index.column() != 0:
            return False
        identifier = self.entries[index.row()].id
        checked = value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value
        if checked and identifier not in self.marked_ids and len(self.marked_ids) >= MAX_BATCH:
            self.limit_reached.emit()
            return False
        if checked:
            self.marked_ids.add(identifier)
        else:
            self.marked_ids.discard(identifier)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.marks_changed.emit()
        return True

    def clear_marks(self):
        self.marked_ids.clear()
        self.refresh()
        self.marks_changed.emit()

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return super().headerData(section, orientation, role)

    def set_project(self, project: Project):
        self.beginResetModel()
        self.entries = project.entries
        self.marked_ids.clear()
        self.endResetModel()
        self.marks_changed.emit()

    def refresh(self):
        if self.entries:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.entries) - 1, 5))


class EntryFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.query = ""
        self.status = "Todos os estados"
        self.kind = "Todos os tipos"
        self.setDynamicSortFilter(False)

    def filterAcceptsRow(self, row, parent):
        entry = self.sourceModel().entries[row]
        return (
            (self.status == "Todos os estados" or self.status == entry.status)
            and (self.kind == "Todos os tipos" or self.kind == entry.kind)
            and (
                not self.query
                or self.query
                in f"{entry.source}\n{entry.translation}\n{entry.file}\n{entry.context}".casefold()
            )
        )


def unique_folder(parent: Path, name: str) -> Path:
    target = parent / name
    suffix = 2
    while target.exists():
        target = parent / f"{name}-{suffix}"
        suffix += 1
    return target


STYLE = """
QWidget { background: #101722; color: #e4edf8; font-family: 'Segoe UI', sans-serif; font-size: 13px; }
QMainWindow { background: #101722; }
QToolBar { border: 0; border-bottom: 1px solid #2b3748; padding: 8px; spacing: 6px; }
QToolButton, QPushButton { background: #202d40; border: 1px solid #34455d; border-radius: 5px; padding: 8px 12px; }
QToolButton:hover, QPushButton:hover { background: #2d405b; border-color: #6ba9ef; }
QToolButton:disabled, QPushButton:disabled { color: #61718a; border-color: #273447; }
QPushButton#primary { background: #2875c7; border-color: #4497ed; font-weight: bold; }
QLineEdit, QComboBox, QPlainTextEdit { background: #172233; border: 1px solid #314157; border-radius: 5px; padding: 7px; selection-background-color: #2863a2; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #65b4ff; }
QTableView { background: #142031; alternate-background-color: #192639; border: 1px solid #2c3a4e; gridline-color: #243246; selection-background-color: #244b76; }
QHeaderView::section { background: #202e42; color: #aec4df; padding: 9px; border: 0; border-bottom: 1px solid #3a4f6b; }
QSplitter::handle { background: #26344a; }
QProgressBar { border: 0; background: #233148; border-radius: 3px; height: 7px; text-align: center; }
QProgressBar::chunk { background: #52b4dd; }
QCheckBox { spacing: 7px; }
QLabel#title { font-size: 26px; font-weight: bold; }
QLabel#subtle { color: #9fb3cd; }
QFrame#summary { background: #1a2b40; border: 1px solid #2e4763; border-radius: 7px; }
QStatusBar { color: #a7bdd7; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project: Project | None = None
        self.current_entry: Entry | None = None
        self.worker: ExtractionWorker | None = None
        self.google_worker: GoogleWorker | None = None
        self.sdk_path: Path | None = None
        self.dirty = False
        self.loading_editor = False
        self.setWindowTitle("Tradutor Ren'Py")
        self.resize(1360, 850)
        self.setMinimumSize(980, 660)
        self.setStyleSheet(STYLE)
        self._build_toolbar()
        self._build_content()
        self._set_project_controls(False)
        self.statusBar().showMessage("Selecione o .exe de um jogo para começar.")

    def _build_toolbar(self):
        toolbar = QToolBar("Projeto", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.actions = {}
        for name, label, callback, shortcut in (
            ("game", "Selecionar jogo .exe", self.select_game, "Ctrl+N"),
            ("open", "Abrir projeto", self.open_project, "Ctrl+O"),
            ("save", "Salvar", self.save_project, "Ctrl+S"),
            ("import", "Importar CSV", self.import_translations, None),
            ("csv", "Exportar CSV", self.export_translations, None),
            ("export", "Gerar tradução", self.generate_translation, "Ctrl+E"),
            ("sdk", "SDK Ren'Py", self.choose_sdk, None),
            ("google", "Traduzir com Google", self.start_google, None),
            ("clear", "Limpar marcações", self.clear_marks, None),
            ("cancel", "Cancelar Google", self.cancel_google, None),
        ):
            action = QAction(label, self)
            action.triggered.connect(callback)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            toolbar.addAction(action)
            self.actions[name] = action
        self.actions["cancel"].setEnabled(False)

    def _build_content(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 18, 20, 12)
        layout.setSpacing(12)
        title = QLabel("Tradutor Ren'Py")
        title.setObjectName("title")
        layout.addWidget(title)
        self.subtitle = QLabel("Extraia os textos do jogo, traduza e revise tudo em um só lugar.")
        self.subtitle.setObjectName("subtle")
        self.subtitle.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.subtitle)
        summary = QFrame()
        summary.setObjectName("summary")
        summary_layout = QHBoxLayout(summary)
        self.summary_label = QLabel("Nenhum projeto aberto")
        self.summary_label.setStyleSheet("background: transparent; font-weight: bold;")
        summary_layout.addWidget(self.summary_label, 1)
        self.language_label = QLabel("Idioma: português brasileiro")
        self.language_label.setStyleSheet("background: transparent; color: #7fc8ed;")
        summary_layout.addWidget(self.language_label)
        layout.addWidget(summary)
        filters = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            "Buscar no original, na tradução, no arquivo ou no contexto…"
        )
        filters.addWidget(self.search, 1)
        self.status_filter = QComboBox()
        self.status_filter.addItems(
            ["Todos os estados", "Pendente", "Traduzido", "Revisado", "Verificar tags"]
        )
        filters.addWidget(self.status_filter)
        self.kind_filter = QComboBox()
        self.kind_filter.addItems(["Todos os tipos", "Diálogo", "Menu", "Interface", "YAML"])
        filters.addWidget(self.kind_filter)
        layout.addLayout(filters)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.model = EntryModel(self)
        self.proxy = EntryFilter(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(36)
        header = self.table.horizontalHeader()
        for column in (0, 1, 2, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        for column in (3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        self.table.selectionModel().currentChanged.connect(self.select_entry)
        splitter.addWidget(self.table)
        editor_panel = QWidget()
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(14, 0, 0, 0)
        self.context_label = QLabel("Selecione um texto para traduzir")
        self.context_label.setWordWrap(True)
        self.context_label.setTextFormat(Qt.TextFormat.PlainText)
        self.context_label.setObjectName("subtle")
        editor_layout.addWidget(self.context_label)
        editor_layout.addWidget(QLabel("ORIGINAL"))
        self.original = QPlainTextEdit()
        self.original.setReadOnly(True)
        self.original.setPlaceholderText("O texto original aparecerá aqui.")
        editor_layout.addWidget(self.original, 1)
        editor_layout.addWidget(QLabel("TRADUÇÃO"))
        self.translation = QPlainTextEdit()
        self.translation.setPlaceholderText("Digite a tradução e preserve [variáveis] e {tags}.")
        self.translation.textChanged.connect(self.translation_changed)
        editor_layout.addWidget(self.translation, 1)
        self.validation = QLabel("")
        self.validation.setWordWrap(True)
        self.validation.setTextFormat(Qt.TextFormat.PlainText)
        editor_layout.addWidget(self.validation)
        self.same_text = QCheckBox("Aplicar a textos Ren'Py iguais")
        self.same_text.setChecked(False)
        self.same_text.setToolTip(
            "Os blocos do SDK permitem traduções diferentes por diálogo. "
            "Marque para reutilizar o mesmo texto em outras ocorrências."
        )
        editor_layout.addWidget(self.same_text)
        controls = QHBoxLayout()
        self.copy_button = QPushButton("Copiar original")
        self.copy_button.clicked.connect(
            lambda: self.translation.setPlainText(self.original.toPlainText())
        )
        controls.addWidget(self.copy_button)
        self.review_button = QPushButton("Revisar e avançar")
        self.review_button.setObjectName("primary")
        self.review_button.setShortcut("Ctrl+Return")
        self.review_button.clicked.connect(self.review_and_next)
        controls.addWidget(self.review_button)
        editor_layout.addLayout(controls)
        navigation = QHBoxLayout()
        previous = QPushButton("← Anterior")
        previous.clicked.connect(lambda: self.navigate(-1))
        following = QPushButton("Próximo →")
        following.clicked.connect(lambda: self.navigate(1))
        navigation.addWidget(previous)
        navigation.addWidget(following)
        editor_layout.addLayout(navigation)
        splitter.addWidget(editor_panel)
        splitter.setSizes([850, 450])
        layout.addWidget(splitter, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.setMaximumBlockCount(500)
        self.log.setPlaceholderText(
            "Como começar: selecione o .exe do jogo e uma pasta para o projeto. "
            "Arquivos RPA, roteiros compilados e YAML serão processados automaticamente."
        )
        layout.addWidget(self.log)
        self.setCentralWidget(central)
        self.search.textChanged.connect(self.apply_filters)
        self.status_filter.currentTextChanged.connect(self.apply_filters)
        self.kind_filter.currentTextChanged.connect(self.apply_filters)
        self.model.marks_changed.connect(self.update_google_controls)
        self.model.limit_reached.connect(
            lambda: QMessageBox.information(
                self, "Limite de seleção", "Marque no máximo 25 textos para o Google Tradutor."
            )
        )
        find_action = QAction(self)
        find_action.setShortcut("Ctrl+F")
        find_action.triggered.connect(self.search.setFocus)
        self.addAction(find_action)

    def _set_project_controls(self, enabled: bool):
        for name in ("save", "import", "csv", "export", "clear"):
            self.actions[name].setEnabled(enabled)
        for widget in (
            self.search,
            self.status_filter,
            self.kind_filter,
            self.translation,
            self.copy_button,
            self.review_button,
        ):
            widget.setEnabled(enabled)
        if enabled:
            self.update_validation()
        self.update_google_controls()

    def show_error(self, error):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Não foi possível concluir")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(str(error))
        box.exec()

    def _maybe_save(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Salvar alterações?",
            "O projeto tem traduções ainda não salvas.",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def select_game(self):
        if not self._maybe_save():
            return
        selected, _ = QFileDialog.getOpenFileName(
            self, "Selecione o executável do jogo", "", "Jogo Ren'Py (*.exe)"
        )
        if not selected:
            return
        parent = QFileDialog.getExistingDirectory(
            self, "Escolha onde salvar o projeto (fora do jogo)"
        )
        if not parent:
            return
        language, accepted = QInputDialog.getText(
            self,
            "Idioma da tradução",
            "Identificador do idioma (exemplo: portuguese_br):",
            text="portuguese_br",
        )
        if not accepted:
            return
        if not LANGUAGE.fullmatch(language):
            self.show_error("Use letras minúsculas, números e sublinhado; comece com uma letra.")
            return
        answer = QMessageBox.question(
            self,
            "Incluir textos YAML?",
            "Deseja incluir textos de arquivos .yml/.yaml?\n\n"
            "Serão incluídos apenas name, description e condition quando o valor "
            "de condition estiver entre aspas simples.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return
        include_yaml = answer == QMessageBox.StandardButton.Yes
        if self.sdk_path is None:
            try:
                self.sdk_path = find_sdk()
            except ValueError as error:
                self.show_error(error)
            if self.sdk_path is None and not self.choose_sdk():
                return
        executable = Path(selected)
        destination = unique_folder(Path(parent), f"{executable.stem}-traducao")
        self._set_project_controls(False)
        self.actions["game"].setEnabled(False)
        self.actions["open"].setEnabled(False)
        self.actions["sdk"].setEnabled(False)
        self.table.setEnabled(False)
        self.progress.show()
        self.log.clear()
        self.log.appendPlainText(f"Criando projeto em {destination}")
        self.worker = ExtractionWorker(
            executable,
            destination,
            language,
            self,
            sdk_path=self.sdk_path,
            include_yaml=include_yaml,
        )
        self.worker.progress.connect(self.log.appendPlainText)
        self.worker.succeeded.connect(self.load_project)
        self.worker.failed.connect(self.show_error)
        self.worker.finished.connect(self.extraction_finished)
        self.worker.start()

    def extraction_finished(self):
        self.progress.hide()
        self.actions["game"].setEnabled(True)
        self.actions["open"].setEnabled(True)
        self.actions["sdk"].setEnabled(True)
        self.table.setEnabled(True)
        self._set_project_controls(self.project is not None)

    def open_project(self):
        if not self._maybe_save():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Abrir projeto", "", "Projeto de tradução (*.json)"
        )
        if filename:
            try:
                self.load_project(Project.load(Path(filename)))
            except Exception as exc:
                self.show_error(exc)

    def load_project(self, project: Project):
        self.current_entry = None
        self.project = project
        self.dirty = False
        self.search.clear()
        self.status_filter.setCurrentIndex(0)
        self.kind_filter.setCurrentIndex(0)
        self.model.set_project(project)
        self.proxy.invalidate()
        self.subtitle.setText(f"{project.game_name} · {project.path}")
        self.language_label.setText(f"Idioma: {project.language}")
        self._set_project_controls(True)
        self.update_summary()
        self.log.appendPlainText(f"Projeto aberto: {len(project.entries)} textos.")
        for warning in project.warnings:
            self.log.appendPlainText(f"Aviso: {warning}")
        if project.warnings:
            self.log.appendPlainText(
                "Confira os avisos: alguns arquivos podem não ter sido incluídos."
            )
        self.table.setCurrentIndex(self.proxy.index(0, 0))

    def select_entry(self, current, previous=QModelIndex()):
        self.loading_editor = True
        try:
            source = self.proxy.mapToSource(current)
            self.current_entry = self.model.entries[source.row()] if source.isValid() else None
            entry = self.current_entry
            self.original.setPlainText(entry.source if entry else "")
            self.translation.setPlainText(entry.translation if entry else "")
            self.context_label.setText(
                f"{entry.file}:{entry.line}\n{entry.context}" if entry else "Selecione um texto"
            )
            self.update_validation()
        finally:
            self.loading_editor = False

    def translation_changed(self):
        if self.loading_editor or self.current_entry is None or self.project is None:
            return
        entry = self.current_entry
        text = self.translation.toPlainText()
        entry.update(text)
        if self.same_text.isChecked() and entry.kind != "YAML":
            for other in self.project.entries:
                if other.kind != "YAML" and other.source == entry.source:
                    other.update(text)
        self.dirty = True
        self.model.refresh()
        self.update_validation()
        self.update_summary()

    def update_validation(self):
        entry = self.current_entry
        issues = entry.issues if entry else []
        self.validation.setText(
            " · ".join(issues)
            if issues
            else "Tags preservadas"
            if entry and entry.translation
            else ""
        )
        self.validation.setStyleSheet("color: #ffbd72;" if issues else "color: #67dfb4;")
        running = self.google_worker is not None and self.google_worker.isRunning()
        self.review_button.setEnabled(
            bool(entry and entry.translation and not issues and not running)
        )

    def update_summary(self):
        if self.project is None:
            return
        counts = self.project.counts
        self.summary_label.setText(
            f"{counts['total']} textos   ·   {counts['translated']} traduzidos   ·   "
            f"{counts['reviewed']} revisados"
        )
        self.setWindowTitle(
            f"{'● ' if self.dirty else ''}{self.project.game_name} — Tradutor Ren'Py"
        )
        self.statusBar().showMessage(
            f"{self.proxy.rowCount()} textos visíveis · Ctrl+Enter revisa e avança"
        )

    def apply_filters(self, *_):
        self.proxy.query = self.search.text().casefold()
        self.proxy.status = self.status_filter.currentText()
        self.proxy.kind = self.kind_filter.currentText()
        self.proxy.invalidate()
        if not self.table.currentIndex().isValid():
            self.table.setCurrentIndex(self.proxy.index(0, 0))
        self.update_summary()

    def review_and_next(self):
        entry = self.current_entry
        if entry is None or not entry.translation or entry.issues:
            return
        entry.update(entry.translation, True)
        self.dirty = True
        self.model.refresh()
        self.update_summary()
        self.navigate(1)

    def navigate(self, direction: int):
        count = self.proxy.rowCount()
        if count:
            row = self.table.currentIndex().row()
            self.table.setCurrentIndex(self.proxy.index(max(0, min(count - 1, row + direction)), 0))

    def save_project(self) -> bool:
        if self.project is None:
            return False
        try:
            self.project.save()
            self.dirty = False
            self.update_summary()
            self.log.appendPlainText(f"Projeto salvo: {self.project.path}")
            return True
        except Exception as exc:
            self.show_error(exc)
            return False

    def import_translations(self):
        if self.project is None:
            return
        selected, _ = QFileDialog.getOpenFileName(self, "Importar traduções", "", "CSV (*.csv)")
        if selected:
            try:
                count = import_csv(self.project, Path(selected))
                self.dirty = True
                self.model.refresh()
                self.select_entry(self.table.currentIndex())
                self.update_summary()
                self.log.appendPlainText(f"{count} traduções importadas. Revise e salve o projeto.")
            except Exception as exc:
                self.show_error(exc)

    def export_translations(self):
        if self.project is None:
            return
        selected, _ = QFileDialog.getSaveFileName(
            self, "Exportar textos", "traducoes.csv", "CSV (*.csv)"
        )
        if selected:
            try:
                export_csv(self.project, Path(selected))
                self.log.appendPlainText(f"CSV exportado: {selected}")
            except Exception as exc:
                self.show_error(exc)

    def generate_translation(self):
        if self.project is None:
            return
        mode, accepted = QInputDialog.getItem(
            self,
            "Gerar tradução",
            "Quais textos incluir?",
            ["Todos os traduzidos", "Somente revisados"],
            editable=False,
        )
        if not accepted:
            return
        parent = QFileDialog.getExistingDirectory(
            self, "Escolha onde salvar a tradução (fora do jogo)"
        )
        if not parent:
            return
        destination = unique_folder(Path(parent), f"{self.project.game_name}-exportacao")
        try:
            export_game(self.project, destination, reviewed_only=mode == "Somente revisados")
            self.log.appendPlainText(f"Tradução gerada: {destination}")
            QMessageBox.information(
                self,
                "Tradução gerada",
                f"Arquivos salvos em:\n{destination}\n\n"
                "Faça backup do jogo e siga o LEIA-ME.txt para instalar a tradução.",
            )
        except Exception as exc:
            self.show_error(exc)

    def closeEvent(self, event):
        if self.google_worker is not None and self.google_worker.isRunning():
            self.google_worker.requestInterruption()
            QMessageBox.information(
                self,
                "Google em andamento",
                "A fila foi cancelada. Aguarde a resposta atual antes de fechar.",
            )
            event.ignore()
            return
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self, "Extração em andamento", "Aguarde a conclusão da extração antes de fechar."
            )
            event.ignore()
        elif self._maybe_save():
            event.accept()
        else:
            event.ignore()

    def choose_sdk(self) -> bool:
        directory = QFileDialog.getExistingDirectory(
            self, "Selecione a pasta do SDK oficial do Ren'Py"
        )
        if not directory:
            return False
        try:
            sdk_launcher(Path(directory))
            self.sdk_path = Path(directory)
            self.log.appendPlainText(f"SDK selecionado: {directory}")
            return True
        except ValueError as error:
            self.show_error(error)
            return False

    def clear_marks(self):
        self.model.clear_marks()

    def update_google_controls(self):
        running = self.google_worker is not None and self.google_worker.isRunning()
        extracting = self.worker is not None and self.worker.isRunning()
        marked = len(self.model.marked_ids)
        self.actions["google"].setEnabled(
            bool(self.project and marked and not running and not extracting)
        )
        self.actions["google"].setText(f"Google ({marked}/25)")

    def start_google(self):
        if self.project is None:
            return
        entries = [entry for entry in self.project.entries if entry.id in self.model.marked_ids]
        if not 1 <= len(entries) <= MAX_BATCH:
            self.show_error("Marque de 1 a 25 textos na coluna Google.")
            return
        if any(entry.translation for entry in entries):
            if (
                QMessageBox.question(
                    self,
                    "Substituir traduções?",
                    "Alguns textos marcados já têm tradução. Deseja substituí-la?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
        target, accepted = QInputDialog.getText(
            self,
            "Idioma do Google",
            "Código de destino (pt, en, es, zh-CN…):",
            text=google_language(self.project.language),
        )
        if not accepted:
            return
        self.google_worker = GoogleWorker(entries, target, self)
        self.google_worker.translated.connect(self.apply_google_result)
        self.google_worker.progress.connect(self.google_progress)
        self.google_worker.failed.connect(
            lambda error: self.log.appendPlainText("Google: " + error)
        )
        self.google_worker.completed.connect(self.google_completed)
        self.google_worker.finished.connect(self.google_finished)
        self._set_project_controls(False)
        for name in ("game", "open", "sdk", "google"):
            self.actions[name].setEnabled(False)
        self.table.setEnabled(False)
        self.actions["cancel"].setEnabled(True)
        self.progress.setRange(0, len(entries))
        self.progress.setValue(0)
        self.progress.show()
        self.log.appendPlainText(f"Enviando {len(entries)} textos ao Google, um por vez.")
        self.google_worker.start()

    def google_progress(self, index: int, total: int):
        self.progress.setValue(index - 1)
        self.statusBar().showMessage(f"Google: traduzindo {index}/{total}…")

    def apply_google_result(self, identifier: str, translated: str):
        if self.project is None:
            return
        entry = next(entry for entry in self.project.entries if entry.id == identifier)
        entry.update(translated, reviewed=False)
        self.model.marked_ids.discard(identifier)
        self.dirty = True
        self.model.refresh()
        if self.current_entry is entry:
            self.select_entry(self.table.currentIndex())
        self.update_summary()

    def google_completed(self, success: int, errors: int):
        self.log.appendPlainText(
            f"Google: {success} traduzidos; {errors} erros. "
            "Revise as traduções e salve o projeto. Textos não concluídos continuam marcados."
        )

    def google_finished(self):
        self.progress.hide()
        self.progress.setRange(0, 0)
        self.actions["cancel"].setEnabled(False)
        for name in ("game", "open", "sdk"):
            self.actions[name].setEnabled(True)
        self.table.setEnabled(True)
        self._set_project_controls(self.project is not None)
        self.update_google_controls()

    def cancel_google(self):
        if self.google_worker is not None:
            self.google_worker.requestInterruption()
            self.actions["cancel"].setEnabled(False)
            self.log.appendPlainText("Cancelamento solicitado; aguardando a resposta atual.")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Tradutor Ren'Py")
    app.setOrganizationName("tradutor-renpy")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
