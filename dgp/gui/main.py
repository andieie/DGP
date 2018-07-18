# -*- coding: utf-8 -*-

import os
import pathlib
import logging
from typing import Union

import PyQt5.QtWidgets as QtWidgets
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QColor
from PyQt5.QtCore import pyqtSignal, pyqtBoundSignal
from PyQt5.QtWidgets import QMainWindow, QProgressDialog, QFileDialog, QWidget

import dgp.core.types.enumerations as enums
from dgp.core.controllers.controller_interfaces import IFlightController, IAirborneController
from dgp.core.controllers.project_controllers import AirborneProjectController
from dgp.core.controllers.flight_controller import FlightController
from dgp.core.controllers.project_treemodel import ProjectTreeModel
from dgp.core.models.project import AirborneProject
from dgp.gui.utils import (ConsoleHandler, LOG_FORMAT, LOG_LEVEL_MAP,
                           LOG_COLOR_MAP, get_project_file)
from dgp.gui.dialogs.create_project_dialog import CreateProjectDialog

from dgp.gui.workspace import FlightTab
from dgp.gui.ui.main_window import Ui_MainWindow


def autosave(method):
    """Decorator to call save_project for functions that alter project state."""
    def enclosed(self, *args, **kwargs):
        if kwargs:
            result = method(self, *args, **kwargs)
        elif len(args) > 1:
            result = method(self, *args)
        else:
            result = method(self)
        self.save_project()
        return result
    return enclosed


class MainWindow(QMainWindow, Ui_MainWindow):
    """An instance of the Main Program Window"""

    # Define signals to allow updating of loading progress
    status = pyqtSignal(str)  # type: pyqtBoundSignal
    progress = pyqtSignal(int)  # type: pyqtBoundSignal

    def __init__(self, project: AirborneProjectController, *args):
        super().__init__(*args)

        self.setupUi(self)
        self.title = 'Dynamic Gravity Processor [*]'
        self.setWindowTitle(self.title)

        # Attach to the root logger to capture all child events
        self.log = logging.getLogger()
        # Setup logging handler to log to GUI panel
        console_handler = ConsoleHandler(self.write_console)
        console_handler.setFormatter(LOG_FORMAT)
        sb_handler = ConsoleHandler(self.show_status)
        sb_handler.setFormatter(logging.Formatter("%(message)s"))
        self.log.addHandler(console_handler)
        self.log.addHandler(sb_handler)
        self.log.setLevel(logging.DEBUG)

        # Setup Project
        self.project = project
        self.project.set_parent_widget(self)
        self.project_model = ProjectTreeModel(self.project)
        self.project_tree.setModel(self.project_model)
        self.project_tree.expandAll()

        # Support for multiple projects
        self.projects = [project]
        self.project_model.tabOpenRequested.connect(self._tab_open_requested)

        # Initialize Variables
        self.import_base_path = pathlib.Path('~').expanduser().joinpath(
            'Desktop')
        self._default_status_timeout = 5000  # Status Msg timeout in milli-sec

        # Issue #50 Flight Tabs
        # flight_tabs is a custom Qt Widget (dgp.gui.workspace) promoted within the .ui file
        self.flight_tabs: QtWidgets.QTabWidget
        self._open_tabs = {}  # Track opened tabs by {uid: tab_widget, ...}

        self._mutated = False

    def _init_slots(self):
        """Initialize PyQt Signals/Slots for UI Buttons and Menus"""

        # Event Signals #
        # self.project_model.flight_changed.connect(self._flight_changed)
        self.project_model.project_changed.connect(self._project_mutated)

        # File Menu Actions #
        self.action_exit.triggered.connect(self.close)
        self.action_file_new.triggered.connect(self.new_project_dialog)
        self.action_file_open.triggered.connect(self.open_project_dialog)
        self.action_file_save.triggered.connect(self.save_project)

        # Project Menu Actions #
        self.action_import_gps.triggered.connect(
            lambda: self.project.load_file_dlg(enums.DataTypes.TRAJECTORY, ))
        self.action_import_grav.triggered.connect(
            lambda: self.project.load_file_dlg(enums.DataTypes.GRAVITY, ))
        self.action_add_flight.triggered.connect(self.project.add_flight)
        self.action_add_meter.triggered.connect(self.project.add_gravimeter)

        # Project Control Buttons #
        self.prj_add_flight.clicked.connect(self.project.add_flight)
        self.prj_add_meter.clicked.connect(self.project.add_gravimeter)
        self.prj_import_gps.clicked.connect(
            lambda: self.project.load_file_dlg(enums.DataTypes.TRAJECTORY, ))
        self.prj_import_grav.clicked.connect(
            lambda: self.project.load_file_dlg(enums.DataTypes.GRAVITY, ))

        # Tab Browser Actions #
        self.flight_tabs.tabCloseRequested.connect(self._tab_close_requested)
        self.flight_tabs.currentChanged.connect(self._tab_changed)

        # Console Window Actions #
        self.combo_console_verbosity.currentIndexChanged[str].connect(
            self.set_logging_level)

    @property
    def current_flight(self):
        """Returns the active flight based on which Flight Tab is in focus."""
        if self.flight_tabs.count() > 0:
            return self.flight_tabs.currentWidget().flight
        return None

    @property
    def current_tab(self) -> Union[FlightTab, None]:
        """Get the active FlightTab (returns None if no Tabs are open)"""
        if self.flight_tabs.count() > 0:
            return self.flight_tabs.currentWidget()
        return None

    def load(self):
        """Called from splash screen to initialize and load main window.
        This may be safely deprecated as we currently do not perform any long
        running operations on initial load as we once did."""
        self._init_slots()
        self.setWindowState(Qt.WindowMaximized)
        self.save_project()
        self.show()
        try:
            self.progress.disconnect()
            self.status.disconnect()
        except TypeError:
            # This can be safely ignored (no slots were connected)
            pass

    def closeEvent(self, *args, **kwargs):
        self.log.info("Saving project and closing.")
        self.save_project()
        super().closeEvent(*args, **kwargs)

    def set_logging_level(self, name: str):
        """PyQt Slot: Changes logging level to passed logging level name."""
        self.log.debug("Changing logging level to: {}".format(name))
        level = LOG_LEVEL_MAP[name.lower()]
        self.log.setLevel(level)

    def write_console(self, text, level):
        """PyQt Slot: Logs a message to the GUI console"""
        log_color = QColor(LOG_COLOR_MAP.get(level.lower(), 'black'))
        self.text_console.setTextColor(log_color)
        self.text_console.append(str(text))
        self.text_console.verticalScrollBar().setValue(
            self.text_console.verticalScrollBar().maximum())

    def show_status(self, text, level):
        """Displays a message in the MainWindow's status bar for specific
        log level events."""
        if level.lower() == 'error' or level.lower() == 'info':
            self.statusBar().showMessage(text, self._default_status_timeout)

    @pyqtSlot(IFlightController, name='_tab_open_requested')
    def _tab_open_requested(self, flight):
        """pyqtSlot(:class:`IFlightController`)

        Open a :class:`FlightTab` if one does not exist, else set the
        FlightTab for the given :class:`IFlightController` to active

        """
        if flight.uid in self._open_tabs:
            self.flight_tabs.setCurrentWidget(self._open_tabs[flight.uid])
        else:
            tab = FlightTab(flight)
            self._open_tabs[flight.uid] = tab
            index = self.flight_tabs.addTab(tab, flight.get_attr('name'))
            self.flight_tabs.setCurrentIndex(index)

    @pyqtSlot(IFlightController, name='_tab_close_requested')
    def _tab_close_requested(self, flight):
        """pyqtSlot(:class:`IFlightController`)

        Close/dispose of the tab for the supplied flight if it exists, else
        do nothing.

        """
        if flight.uid in self._open_tabs:
            self.log.debug(f'Tab close requested for flight '
                           f'{flight.get_attr("name")}')
            tab = self._open_tabs[flight.uid]
            index = self.flight_tabs.indexOf(tab)
            self.flight_tabs.removeTab(index)
            del self._open_tabs[flight.uid]

    @pyqtSlot(int, name='_tab_close_requested')
    def _tab_close_requested(self, index):
        """pyqtSlot(int)

        Close/dispose of tab specified by int index.
        This slot is used to handle user interaction when clicking the close (x)
        button on an opened tab.

        """
        self.log.debug(f'Tab close requested for tab at index {index}')
        tab = self.flight_tabs.widget(index)  # type: FlightTab
        del self._open_tabs[tab.uid]
        self.flight_tabs.removeTab(index)


    # @pyqtSlot(FlightController, name='_flight_changed')
    # def _flight_changed(self, flight: FlightController):
    #     if flight.uid in self._open_tabs:
    #         self.flight_tabs.setCurrentWidget(self._open_tabs[flight.uid])
    #     else:
    #         flt_tab = FlightTab(flight)
    #         self._open_tabs[flight.uid] = flt_tab
    #         idx = self.flight_tabs.addTab(flt_tab, flight.get_attr('name'))
    #         self.flight_tabs.setCurrentIndex(idx)

    @pyqtSlot(name='_project_mutated')
    def _project_mutated(self):
        print("Project mutated")
        self._mutated = True
        self.setWindowModified(True)

    @pyqtSlot(int, name='_tab_changed')
    def _tab_changed(self, index: int):
        self.log.debug("Tab index changed to %d", index)
        current = self.flight_tabs.currentWidget()
        if current is not None:
            fc = current.flight  # type: FlightController
            self.project.set_active_child(fc, emit=False)
        else:
            self.log.debug("No flight tab open")

    @pyqtSlot(int, name='_tab_closed')
    def _tab_closed(self, index: int):
        self.log.debug("Tab close requested for tab: {}".format(index))
        tab = self.flight_tabs.widget(index)  # type: FlightTab
        del self._open_tabs[tab.uid]
        self.flight_tabs.removeTab(index)

    def show_progress_dialog(self, title, start=0, stop=1, label=None,
                             cancel="Cancel", modal=False,
                             flags=None) -> QProgressDialog:
        """Generate a progress bar to show progress on long running event."""
        if flags is None:
            flags = (Qt.WindowSystemMenuHint |
                     Qt.WindowTitleHint |
                     Qt.WindowMinimizeButtonHint)

        dialog = QProgressDialog(label, cancel, start, stop, self, flags)
        dialog.setWindowTitle(title)
        dialog.setModal(modal)
        dialog.setMinimumDuration(0)
        # dialog.setCancelButton(None)
        dialog.setValue(1)
        dialog.show()
        return dialog

    def show_progress_status(self, start, stop, label=None) -> QtWidgets.QProgressBar:
        """Show a progress bar in the windows Status Bar"""
        label = label or 'Loading'
        sb = self.statusBar()  # type: QtWidgets.QStatusBar
        progress = QtWidgets.QProgressBar(self)
        progress.setRange(start, stop)
        progress.setAttribute(Qt.WA_DeleteOnClose)
        progress.setToolTip(label)
        sb.addWidget(progress)
        return progress

    def save_project(self) -> None:
        if self.project is None:
            return
        if self.project.save():
            # self.setWindowTitle(self.title + ' - {} [*]'
            #                     .format(self.project.name))
            self.setWindowModified(False)
            self.log.info("Project saved.")
        else:
            self.log.info("Error saving project.")

    # Project dialog functions ################################################

    def new_project_dialog(self) -> QMainWindow:
        new_window = True
        dialog = CreateProjectDialog()
        if dialog.exec_():
            self.log.info("Creating new project")
            project = dialog.project
            if new_window:
                self.log.debug("Opening project in new window")
                return MainWindow(project)
            else:
                self.project = project
                self.project.save()
                self.update_project()

    # TODO: This will eventually require a dialog to allow selection of project
    # type, or a metadata file in the project directory specifying type info
    def open_project_dialog(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open Project Directory",
                                                os.path.abspath('..'))
        if not path:
            return

        prj_file = get_project_file(path)
        if prj_file is None:
            self.log.warning("No project file's found in directory: {}"
                             .format(path))
            return
        self.save_project()
        with open(prj_file, 'r') as fd:
            self.project = AirborneProject.from_json(fd.read())
        self.update_project()
        return
