# coding: utf-8

import os
import logging
import functools
import datetime
import pathlib
from typing import Dict, Union, List

from PyQt5 import Qt, QtWidgets, QtCore
from PyQt5.uic import loadUiType

import dgp.lib.project as prj
from dgp.gui.models import TableModel, SelectionDelegate
from dgp.gui.utils import ConsoleHandler, LOG_COLOR_MAP
from dgp.lib.etc import gen_uuid


data_dialog, _ = loadUiType('dgp/gui/ui/data_import_dialog.ui')
advanced_import, _ = loadUiType('dgp/gui/ui/advanced_data_import.ui')
flight_dialog, _ = loadUiType('dgp/gui/ui/add_flight_dialog.ui')
project_dialog, _ = loadUiType('dgp/gui/ui/project_dialog.ui')
info_dialog, _ = loadUiType('dgp/gui/ui/info_dialog.ui')
line_label_dialog, _ = loadUiType('dgp/gui/ui/set_line_label.ui')


class BaseDialog(QtWidgets.QDialog):
    def __init__(self):
        self.log = logging.getLogger(__name__)
        error_handler = ConsoleHandler(self.write_error)
        error_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        error_handler.setLevel(logging.DEBUG)
        self.log.addHandler(error_handler)
        pass


class ImportData(QtWidgets.QDialog, data_dialog):
    """
    Rationalization:
    This dialog will be used to import gravity and/or GPS data.
    A drop down box will be populated with the available project flights into which the data will be associated
    User will specify wheter the data is a gravity or gps file (TODO: maybe we can programatically determine the type)
    User will specify file path
        Maybe we can dynamically load the first 5 or so lines of data and display column headings, which would allow user
        to change the headers if necesarry

    This class does not handle the actual loading of data, it only sets up the parameters (path, type etc) for the
    calling class to do the loading.
    """
    def __init__(self, project: prj.AirborneProject=None, flight: prj.Flight=None, *args):
        """

        :param project:
        :param flight: Currently selected flight to auto-select in list box
        :param args:
        """
        super().__init__(*args)
        self.setupUi(self)

        # Setup button actions
        self.button_browse.clicked.connect(self.browse_file)
        self.buttonBox.accepted.connect(self.accept)

        dgsico = Qt.QIcon(':images/assets/geoid_icon.png')

        self.setWindowIcon(dgsico)
        self.path = None
        self.dtype = None
        self.flight = flight

        for flight in project.flights:
            # TODO: Change dict index to human readable value
            self.combo_flights.addItem(flight.name, flight.uid)
            if flight == self.flight:  # scroll to this item if it matches self.flight
                self.combo_flights.setCurrentIndex(self.combo_flights.count() - 1)
        for meter in project.meters:
            self.combo_meters.addItem(meter.name)

        self.file_model = Qt.QFileSystemModel()
        self.init_tree()

    def init_tree(self):
        self.file_model.setRootPath(os.getcwd())
        self.file_model.setNameFilters(["*.csv", "*.dat"])

        self.tree_directory.setModel(self.file_model)
        self.tree_directory.scrollTo(self.file_model.index(os.getcwd()))

        self.tree_directory.resizeColumnToContents(0)
        for i in range(1, 4):  # Remove size/date/type columns from view
            self.tree_directory.hideColumn(i)
        self.tree_directory.clicked.connect(self.select_tree_file)

    def select_tree_file(self, index):
        path = pathlib.Path(self.file_model.filePath(index))
        # TODO: Verify extensions for selected files before setting below
        if path.is_file():
            self.field_path.setText(str(path.resolve()))
            self.path = path
        else:
            return

    def browse_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Data File", os.getcwd(), "Data (*.dat *.csv)")
        if path:
            self.path = pathlib.Path(path)
            self.field_path.setText(self.path.name)
            index = self.file_model.index(str(self.path.resolve()))
            self.tree_directory.scrollTo(self.file_model.index(str(self.path.resolve())))
            self.tree_directory.setCurrentIndex(index)

    def accept(self):
        # '&' is used to set text hints in the GUI
        self.dtype = {'G&PS Data': 'gps', '&Gravity Data': 'gravity'}.get(self.group_radiotype.checkedButton().text(),
                                                                          'gravity')
        self.flight = self.combo_flights.currentData()
        if self.path is None:
            return
        super().accept()

    @property
    def content(self) -> (pathlib.Path, str, prj.Flight):
        return self.path, self.dtype, self.flight


class AdvancedImport(QtWidgets.QDialog, advanced_import):
    def __init__(self, project, flight, parent=None):
        """

        Parameters
        ----------
        project : GravityProject
            Parent project
        flight : Flight
            Currently selected flight when Import button was clicked
        parent : QWidget
            Parent Widget
        """
        super().__init__(parent=parent)
        self.setupUi(self)
        self._preview_limit = 5
        self._project = project
        self._path = None
        self._flight = flight

        for flt in project.flights:
            self.combo_flights.addItem(flt.name, flt)
            if flt == self._flight:  # scroll to this item if it matches self.flight
                self.combo_flights.setCurrentIndex(self.combo_flights.count() - 1)

        # Signals/Slots
        self.line_path.textChanged.connect(self._preview)
        self.btn_browse.clicked.connect(self.browse_file)
        self.btn_setcols.clicked.connect(self._capture)
        # This doesn't work, as the partial function is created with self._path which is None
        # self.btn_reload.clicked.connect(functools.partial(self._preview, self._path))

    @property
    def content(self) -> (str, str, List, prj.Flight):
        return self._path, self._dtype(), self._capture(), self._flight

    def accept(self) -> None:
        self._flight = self.combo_flights.currentData()
        super().accept()
        return

    def _capture(self) -> Union[None, List]:
        table = self.table_preview  # type: QtWidgets.QTableView
        model = table.model()  # type: TableModel
        if model is None:
            return None
        print("Row 0 {}".format(model.get_row(0)))
        fields = model.get_row(0)
        return fields

    def _dtype(self):
        return {'GPS': 'gps', 'Gravity': 'gravity'}.get(self.group_dtype.checkedButton().text().replace('&', ''),
                                                        'gravity')

    def _preview(self, path: str):
        if path is None:
            return
        path = pathlib.Path(path)
        if not path.exists():
            print("Path doesn't exist")
            return
        lines = []
        with path.open('r') as fd:
            for i, line in enumerate(fd):
                cells = line.split(',')
                lines.append(cells)
                if i >= self._preview_limit:
                    break

        dtype = self._dtype()
        if dtype == 'gravity':
            fields = ['gravity', 'long', 'cross', 'beam', 'temp', 'status', 'pressure',
                      'Etemp', 'GPSweek', 'GPSweekseconds']
        elif dtype == 'gps':
            fields = ['mdy', 'hms', 'lat', 'long', 'ell_ht', 'ortho_ht', 'num_sats', 'pdop']
        else:
            return
        delegate = SelectionDelegate(fields)
        model = TableModel(fields, editheader=True)
        model.append(*fields)
        for line in lines:
            model.append(*line)
        self.table_preview.setModel(model)
        self.table_preview.setItemDelegate(delegate)

    def browse_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Data File", os.getcwd(),
                                                        "Data (*.dat *.csv *.txt)")
        if path:
            self.line_path.setText(str(path))
            self._path = path


class AddFlight(QtWidgets.QDialog, flight_dialog):
    def __init__(self, project, *args):
        super().__init__(*args)
        self.setupUi(self)
        self._project = project
        self._flight = None
        self._grav_path = None
        self._gps_path = None
        self.combo_meter.addItems(project.meters)
        self.browse_gravity.clicked.connect(functools.partial(self.browse, field=self.path_gravity))
        self.browse_gps.clicked.connect(functools.partial(self.browse, field=self.path_gps))
        self.date_flight.setDate(datetime.datetime.today())
        self._uid = gen_uuid('f')
        self.text_uuid.setText(self._uid)

        self.params_model = TableModel(['Key', 'Start Value', 'End Value'], editable=[1, 2])
        self.params_model.append('Tie Location')
        self.params_model.append('Tie Reading')
        self.flight_params.setModel(self.params_model)

    def accept(self):
        qdate = self.date_flight.date()  # type: QtCore.QDate
        date = datetime.date(qdate.year(), qdate.month(), qdate.day())
        self._grav_path = self.path_gravity.text()
        self._gps_path = self.path_gps.text()
        self._flight = prj.Flight(self._project, self.text_name.text(), self._project.get_meter(
            self.combo_meter.currentText()), uuid=self._uid, date=date)
        print(self.params_model.updates)
        super().accept()

    def browse(self, field):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Data File", os.getcwd(),
                                                        "Data (*.dat *.csv *.txt)")
        if path:
            field.setText(path)

    @property
    def flight(self):
        return self._flight

    @property
    def gps(self):
        if self._gps_path is not None and len(self._gps_path) > 0:
            return pathlib.Path(self._gps_path)
        return None

    @property
    def gravity(self):
        if self._grav_path is not None and len(self._grav_path) > 0:
            return pathlib.Path(self._grav_path)
        return None


class CreateProject(QtWidgets.QDialog, project_dialog):
    def __init__(self, *args):
        super().__init__(*args)
        self.setupUi(self)

        # TODO: Abstract logging setup to a base dialog class so that it can be easily implemented in all dialogs
        self.log = logging.getLogger(__name__)
        error_handler = ConsoleHandler(self.write_error)
        error_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
        error_handler.setLevel(logging.DEBUG)
        self.log.addHandler(error_handler)

        self.prj_create.clicked.connect(self.create_project)
        self.prj_browse.clicked.connect(self.select_dir)
        self.prj_desktop.clicked.connect(self._select_desktop)

        self._project = None

        # Populate the type selection list
        dgs_airborne = Qt.QListWidgetItem(Qt.QIcon(':images/assets/flight_icon.png'), 'DGS Airborne', self.prj_type_list)
        dgs_airborne.setData(QtCore.Qt.UserRole, 'dgs_airborne')
        self.prj_type_list.setCurrentItem(dgs_airborne)
        dgs_marine = Qt.QListWidgetItem(Qt.QIcon(':images/assets/boat_icon.png'), 'DGS Marine', self.prj_type_list)
        dgs_marine.setData(QtCore.Qt.UserRole, 'dgs_marine')

    def write_error(self, msg, level=None) -> None:
        self.label_required.setText(msg)
        self.label_required.setStyleSheet('color: {}'.format(LOG_COLOR_MAP[level]))

    def create_project(self):
        """
        Called upon 'Create' button push, do some basic validation of fields then
        accept() if required fields are filled, otherwise color the labels red
        :return: None
        """
        required_fields = {'prj_name': 'label_name', 'prj_dir': 'label_dir'}

        invalid_input = False
        for attr in required_fields.keys():
            if not self.__getattribute__(attr).text():
                self.__getattribute__(required_fields[attr]).setStyleSheet('color: red')
                invalid_input = True
            else:
                self.__getattribute__(required_fields[attr]).setStyleSheet('color: black')

        if not pathlib.Path(self.prj_dir.text()).exists():
            invalid_input = True
            self.label_dir.setStyleSheet('color: red')
            self.log.error("Invalid Directory")

        if invalid_input:
            return

        if self.prj_type_list.currentItem().data(QtCore.Qt.UserRole) == 'dgs_airborne':
            name = str(self.prj_name.text()).rstrip()
            path = pathlib.Path(self.prj_dir.text()).joinpath(name)
            if not path.exists():
                path.mkdir(parents=True)
            self._project = prj.AirborneProject(path, name,
                                                self.prj_description.toPlainText().rstrip())
        else:
            self.log.error("Invalid Project Type (Not Implemented)")
            return

        self.accept()

    def _select_desktop(self):
        path = pathlib.Path().home().joinpath('Desktop')
        self.prj_dir.setText(str(path))

    def select_dir(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Project Parent Directory")
        if path:
            self.prj_dir.setText(path)

    @property
    def project(self):
        return self._project


class InfoDialog(QtWidgets.QDialog, info_dialog):
    def __init__(self, model, parent=None, **kwargs):
        super().__init__(parent=parent, **kwargs)
        self.setupUi(self)
        self._model = model
        self.setModel(self._model)
        self.updates = None

    def setModel(self, model):
        table = self.table_info  # type: QtWidgets.QTableView
        table.setModel(model)
        table.resizeColumnsToContents()
        width = 50
        for col_idx in range(table.colorCount()):
            width += table.columnWidth(col_idx)
        self.resize(width, self.height())

    def accept(self):
        self.updates = self._model.updates
        super().accept()

class SetLineLabelDialog(QtWidgets.QDialog, line_label_dialog):
    def __init__(self, label):
        super().__init__()
        self.setupUi(self)

        self._label = label

        if self._label is not None:
            self.label_txt.setText(self._label)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

    def accept(self):
        text = self.label_txt.text().strip()
        if text:
            self._label = text
        else:
            self._label = None
        super().accept()

    def reject(self):
        super().reject()

    @property
    def label_text(self):
        return self._label