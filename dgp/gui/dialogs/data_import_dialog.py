# -*- coding: utf-8 -*-
import csv
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Union, Optional, List

from PyQt5.QtCore import Qt, pyqtSlot, pyqtSignal, QDate, QRegExp
from PyQt5.QtGui import QStandardItemModel, QStandardItem, QIcon, QRegExpValidator
from PyQt5.QtWidgets import QDialog, QFileDialog, QListWidgetItem, QCalendarWidget, QWidget, QFormLayout

from dgp.core import Icon, DataType
from dgp.core.controllers.gravimeter_controller import GravimeterController
from dgp.core.controllers.dataset_controller import DataSetController
from dgp.core.controllers.controller_interfaces import IAirborneController, IFlightController, IDataSetController
from dgp.core.models.datafile import DataFile
from dgp.gui.ui.data_import_dialog import Ui_DataImportDialog
from .dialog_mixins import FormValidator
from .custom_validators import FileExistsValidator

__all__ = ['DataImportDialog']


class DataImportDialog(QDialog, Ui_DataImportDialog, FormValidator):

    load = pyqtSignal(DataFile, dict, DataSetController)

    def __init__(self, project: IAirborneController,
                 datatype: DataType, base_path: str = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent=parent)
        self.setupUi(self)
        self.log = logging.getLogger(__name__)

        self._project = project
        self._datatype = datatype
        self._base_path = base_path or str(Path().home().resolve())
        self._type_map = {DataType.GRAVITY: 0, DataType.TRAJECTORY: 1}
        self._type_filters = {DataType.GRAVITY: "Gravity (*.dat *.csv);;Any (*.*)",
                              DataType.TRAJECTORY: "Trajectory (*.dat *.csv *.txt);;Any (*.*)"}

        # Declare parameter names and values mapped from the dialog for specific DataType
        # These match up with the methods in trajectory/gravity_ingestor
        self._params_map = {
            DataType.GRAVITY: {
                'columns': lambda: None,  # TODO: Change in future based on Sensor Type
                'interp': lambda: self.qchb_grav_interp.isChecked(),
                'skiprows': lambda: 1 if self.qchb_grav_hasheader.isChecked() else 0
            },
            DataType.TRAJECTORY: {
                'timeformat': lambda: self.qcb_traj_timeformat.currentText().lower(),
                'columns': lambda: self.qcb_traj_timeformat.currentData(Qt.UserRole),
                'skiprows': lambda: 1 if self.qchb_traj_hasheader.isChecked() else 0,
                'is_utc': lambda: self.qchb_traj_isutc.isChecked()
            }
        }

        self._gravity = QListWidgetItem(Icon.GRAVITY.icon(), "Gravity")
        self._gravity.setData(Qt.UserRole, DataType.GRAVITY)
        self._trajectory = QListWidgetItem(Icon.TRAJECTORY.icon(), "Trajectory")
        self._trajectory.setData(Qt.UserRole, DataType.TRAJECTORY)

        self.qlw_datatype.addItem(self._gravity)
        self.qlw_datatype.addItem(self._trajectory)
        self.qlw_datatype.setCurrentRow(self._type_map.get(datatype, 0))

        self.qcb_flight.currentIndexChanged.connect(self._flight_changed)
        self.qcb_flight.setModel(self.project.flight_model)

        self.qde_date.setDate(datetime.today())
        self._calendar = QCalendarWidget()
        self.qde_date.setCalendarWidget(self._calendar)
        self.qde_date.setCalendarPopup(True)
        self.qpb_date_from_flight.clicked.connect(self._set_date)

        # Gravity Widget
        self.qcb_gravimeter.currentIndexChanged.connect(self._gravimeter_changed)
        self._meter_model = self.project.meter_model  # type: QStandardItemModel
        self.qcb_gravimeter.setModel(self._meter_model)
        self.qpb_add_sensor.clicked.connect(self.project.add_gravimeter_dlg)
        # if self._meter_model.rowCount() == 0:
        #     print("NO meters available")
        self.qcb_gravimeter.setCurrentIndex(0)

        # Trajectory Widget
        self._traj_timeformat_model = QStandardItemModel()
        self.qcb_traj_timeformat.setModel(self._traj_timeformat_model)
        self.qcb_traj_timeformat.currentIndexChanged.connect(self._traj_timeformat_changed)
        sow = QStandardItem("SOW")
        sow.setData(['week', 'sow', 'lat', 'long', 'ell_ht'], Qt.UserRole)
        hms = QStandardItem("HMS")
        hms.setData(['mdy', 'hms', 'lat', 'long', 'ell_ht'], Qt.UserRole)
        serial = QStandardItem("Serial")
        serial.setData(['datenum', 'lat', 'long', 'ell_ht'], Qt.UserRole)
        self._traj_timeformat_model.appendRow(hms)
        self._traj_timeformat_model.appendRow(sow)
        self._traj_timeformat_model.appendRow(serial)

        # Signal connections
        self.qle_filepath.textChanged.connect(self._filepath_changed)
        self.qlw_datatype.currentItemChanged.connect(self._datatype_changed)
        self.qpb_browse.clicked.connect(self._browse)
        self.qpb_add_flight.clicked.connect(self.project.add_flight_dlg)

        self.qsw_advanced_properties.setCurrentIndex(self._type_map[datatype])

        # Configure Validators
        self.qle_filepath.setValidator(FileExistsValidator())
        self.qcb_dataset.setValidator(QRegExpValidator(QRegExp("[A-Za-z]\+")))

    def set_initial_flight(self, flight: IFlightController):
        for i in range(self.qcb_flight.model().rowCount()):  # pragma: no branch
            child = self.qcb_flight.model().item(i, 0)
            if child.uid == flight.uid:  # pragma: no branch
                self.qcb_flight.setCurrentIndex(i)
                break

    @property
    def validation_targets(self) -> List[QFormLayout]:
        return [self.qfl_common]

    @property
    def validation_error(self):
        return self.ql_validation_err

    @property
    def project(self) -> IAirborneController:
        return self._project

    @property
    def flight(self) -> IFlightController:
        fc = self.qcb_flight.model().item(self.qcb_flight.currentIndex())
        return self.project.get_child(fc.uid)

    @property
    def dataset(self) -> IDataSetController:
        model: QStandardItemModel = self.qcb_dataset.model()
        dsc: IDataSetController = model.item(self.qcb_dataset.currentIndex())
        return self.flight.get_child(dsc.uid)

    @property
    def file_path(self) -> Union[Path, None]:
        if not len(self.qle_filepath.text()):
            return None
        return Path(self.qle_filepath.text())

    @property
    def datatype(self) -> DataType:
        return self.qlw_datatype.currentItem().data(Qt.UserRole)

    @property
    def _browse_path(self):
        return self.file_path or self._base_path

    @property
    def date(self) -> datetime:
        _date: QDate = self.qde_date.date()
        return datetime(_date.year(), _date.month(), _date.day())

    def accept(self):  # pragma: no cover
        if not self.validate(empty_combo_ok=False):
            print("Dialog input not valid")
            return

        file = DataFile(self.datatype, date=self.date,
                        source_path=self.file_path, name=self.qle_rename.text())
        param_map = self._params_map[self.datatype]
        params = {key: value() for key, value in param_map.items()}
        self.load.emit(file, params, self.dataset)

        if self.qchb_copy_file.isChecked():
            self._copy_file()
        return super().accept()

    def _copy_file(self):  # pragma: no cover
        src = self.file_path
        dest_name = src.name
        if self.qle_rename.text():
            dest_name = self.qle_rename.text() + '.dat'

        dest = self.project.path.resolve().joinpath(dest_name)
        try:
            shutil.copy(src, dest)
        except IOError:
            self.log.exception("Unable to copy source file to project directory.")

    def _set_date(self):
        self.qde_date.setDate(self.flight.get_attr('date'))

    @pyqtSlot(name='_browse')
    def _browse(self):  # pragma: no cover
        path, _ = QFileDialog.getOpenFileName(self, "Browse for data file",
                                              str(self._browse_path),
                                              self._type_filters[self._datatype])
        if path:
            self.qle_filepath.setText(path)

    @pyqtSlot(QListWidgetItem, QListWidgetItem, name='_datatype_changed')
    def _datatype_changed(self, current: QListWidgetItem, previous: QListWidgetItem):  # pragma: no cover
        self._datatype = current.data(Qt.UserRole)
        self.qsw_advanced_properties.setCurrentIndex(self._type_map[self._datatype])

    @pyqtSlot(str, name='_filepath_changed')
    def _filepath_changed(self, text: str):  # pragma: no cover
        """
        Detect attributes of file and display them in the dialog info section
        """
        path = Path(text)
        if not path.is_file():
            return
        self.qle_filename.setText(path.name)
        st_size_mib = path.stat().st_size / 1048576  # 1024 ** 2
        self.qle_filesize.setText("{:.3f} MiB".format(st_size_mib))
        with path.open(mode='r', newline='') as fd:
            try:
                has_header = csv.Sniffer().has_header(fd.read(8192))
            except csv.Error:
                has_header = False
            print("File has header row: " + str(has_header))
            fd.seek(0)

            # Detect line count
            lines = fd.readlines()
            line_count = len(lines)
            col_count = len(lines[0].split(','))
        self.qle_linecount.setText(str(line_count))
        self.qle_colcount.setText(str(col_count))

    @pyqtSlot(int, name='_gravimeter_changed')
    def _gravimeter_changed(self, index: int):  # pragma: no cover
        meter_ctrl = self.project.meter_model.item(index)
        if not meter_ctrl:
            self.log.debug("No meter available")
            return
        if isinstance(meter_ctrl, GravimeterController):
            sensor_type = meter_ctrl.get_attr('type') or "Unknown"
            self.qle_sensortype.setText(sensor_type)
            self.qle_grav_format.setText(meter_ctrl.get_attr('column_format'))

    @pyqtSlot(int, name='_traj_timeformat_changed')
    def _traj_timeformat_changed(self, index: int):  # pragma: no cover
        timefmt = self._traj_timeformat_model.item(index)
        cols = ', '.join(timefmt.data(Qt.UserRole))
        self.qle_traj_format.setText(cols)

    @pyqtSlot(int, name='_flight_changed')
    def _flight_changed(self, row: int):
        self.qcb_dataset.setModel(self.flight.datasets)

