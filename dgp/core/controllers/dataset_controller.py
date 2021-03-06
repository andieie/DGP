# -*- coding: utf-8 -*-
import logging
import warnings
import weakref
from pathlib import Path
from typing import List, Union, Set, cast

from PyQt5.QtWidgets import QInputDialog
from pandas import DataFrame, Timestamp, concat
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QStandardItemModel, QStandardItem

from dgp.core import OID, Icon
from dgp.core.hdf5_manager import HDF5Manager
from dgp.core.models.datafile import DataFile
from dgp.core.models.dataset import DataSet, DataSegment
from dgp.core.types.enumerations import DataType
from dgp.lib.etc import align_frames
from dgp.gui.plotting.helpers import LineUpdate

from . import controller_helpers
from .gravimeter_controller import GravimeterController
from .controller_interfaces import IFlightController, IDataSetController, VirtualBaseController
from .project_containers import ProjectFolder
from .datafile_controller import DataFileController

_log = logging.getLogger(__name__)


class DataSegmentController(VirtualBaseController):
    """Controller for :class:`DataSegment`

    Implements reference tracking feature allowing the mutation of segments
    representations displayed on a plot surface.
    """
    def __init__(self, segment: DataSegment, project,
                 parent: IDataSetController = None):
        super().__init__(segment, project, parent=parent)
        self.update()

        self._menu = [
            ('addAction', ('Delete', self._action_delete)),
            ('addAction', ('Properties', self._action_properties))
        ]

    @property
    def entity(self) -> DataSegment:
        return cast(DataSegment, super().entity)

    @property
    def menu(self):
        return self._menu

    def clone(self) -> 'DataSegmentController':
        clone = DataSegmentController(self.entity, self.project, self.get_parent())
        self.register_clone(clone)
        return clone

    def _action_delete(self):
        self.get_parent().remove_child(self.uid, confirm=True)

    def update(self):
        super().update()
        self.setText(str(self.entity))
        self.setToolTip(repr(self.entity))

    def _action_properties(self):
        warnings.warn("Properties feature not yet implemented")


class DataSetController(IDataSetController):
    def __init__(self, dataset: DataSet, project, flight: IFlightController):
        super().__init__(model=dataset, project=project, parent=flight)

        self.setIcon(Icon.PLOT_LINE.icon())
        self._grav_file = DataFileController(self.entity.gravity, self.project, self)
        self._traj_file = DataFileController(self.entity.trajectory, self.project, self)
        self._child_map = {DataType.GRAVITY: self._grav_file,
                           DataType.TRAJECTORY: self._traj_file}

        self._segments = ProjectFolder("Segments", Icon.LINE_MODE.icon())
        for segment in dataset.segments:
            seg_ctrl = DataSegmentController(segment, project, parent=self)
            self._segments.appendRow(seg_ctrl)

        self.appendRow(self._grav_file)
        self.appendRow(self._traj_file)
        self.appendRow(self._segments)

        self._sensor = None
        if dataset.sensor is not None:
            ctrl = self.project.get_child(dataset.sensor.uid)
            if ctrl is not None:
                self._sensor = ctrl.clone()
                self.appendRow(self._sensor)

        self._gravity: DataFrame = DataFrame()
        self._trajectory: DataFrame = DataFrame()
        self._dataframe: DataFrame = DataFrame()

        self._channel_model = QStandardItemModel()

        self._menu_bindings = [  # pragma: no cover
            ('addAction', ('Open', lambda: self.model().item_activated(self.index()))),
            ('addAction', ('Set Name', self._action_set_name)),
            ('addAction', (Icon.METER.icon(), 'Set Sensor',
                           self._action_set_sensor_dlg)),
            ('addSeparator', ()),
            ('addAction', (Icon.GRAVITY.icon(), 'Import Gravity',
                           lambda: self.project.load_file_dlg(DataType.GRAVITY, dataset=self))),
            ('addAction', (Icon.TRAJECTORY.icon(), 'Import Trajectory',
                           lambda: self.project.load_file_dlg(DataType.TRAJECTORY, dataset=self))),
            ('addAction', ('Align Data', self.align)),
            ('addSeparator', ()),
            ('addAction', ('Delete', self._action_delete)),
            ('addAction', ('Properties', self._action_properties))
        ]

        self._clones: Set[DataSetController] = weakref.WeakSet()

    def clone(self):
        clone = DataSetController(self.entity, self.get_parent(), self.project)
        self.register_clone(clone)
        return clone

    @property
    def entity(self) -> DataSet:
        return cast(DataSet, super().entity)

    @property
    def menu(self):  # pragma: no cover
        return self._menu_bindings

    @property
    def hdfpath(self) -> Path:
        return self.project.hdfpath

    @property
    def series_model(self) -> QStandardItemModel:
        if 0 == self._channel_model.rowCount():
            self._update_channel_model()
        return self._channel_model

    @property
    def segment_model(self) -> QStandardItemModel:  # pragma: no cover
        return self._segments.internal_model

    @property
    def columns(self) -> List[str]:
        return [col for col in self.dataframe()]

    def _update_channel_model(self):
        df = self.dataframe()
        self._channel_model.clear()
        for col in df:
            series_item = QStandardItem(col)
            series_item.setData(df[col], Qt.UserRole)
            self._channel_model.appendRow(series_item)

    @property
    def gravity(self) -> Union[DataFrame]:
        if not self._gravity.empty:
            return self._gravity
        if self.entity.gravity is None:
            return self._gravity
        try:
            self._gravity = HDF5Manager.load_data(self.entity.gravity, self.hdfpath)
        except Exception:
            _log.exception(f'Exception loading gravity from HDF')
        finally:
            return self._gravity

    @property
    def trajectory(self) -> Union[DataFrame, None]:
        if not self._trajectory.empty:
            return self._trajectory
        if self.entity.trajectory is None:
            return self._trajectory
        try:
            self._trajectory = HDF5Manager.load_data(self.entity.trajectory, self.hdfpath)
        except Exception:
            _log.exception(f'Exception loading trajectory data from HDF')
        finally:
            return self._trajectory

    def dataframe(self) -> DataFrame:
        if self._dataframe.empty:
            self._dataframe: DataFrame = concat([self.gravity, self.trajectory], axis=1, sort=True)
        return self._dataframe

    def align(self):  # pragma: no cover
        """
        TODO: Utility of this is questionable, is it built into transform graphs?
        """
        if self.gravity.empty or self.trajectory.empty:
            _log.info(f'Gravity or Trajectory is empty, cannot align.')
            return
        from dgp.lib.gravity_ingestor import DGS_AT1A_INTERP_FIELDS
        from dgp.lib.trajectory_ingestor import TRAJECTORY_INTERP_FIELDS

        fields = DGS_AT1A_INTERP_FIELDS | TRAJECTORY_INTERP_FIELDS
        n_grav, n_traj = align_frames(self._gravity, self._trajectory,
                                      interp_only=fields)
        self._gravity = n_grav
        self._trajectory = n_traj
        _log.info(f'DataFrame aligned.')

    def add_datafile(self, datafile: DataFile) -> None:
        if datafile.group is DataType.GRAVITY:
            self.entity.gravity = datafile
            self._grav_file.set_datafile(datafile)
            self._gravity = DataFrame()
        elif datafile.group is DataType.TRAJECTORY:
            self.entity.trajectory = datafile
            self._traj_file.set_datafile(datafile)
            self._trajectory = DataFrame()
        else:
            raise TypeError("Invalid DataFile group provided.")

        self._dataframe = DataFrame()
        self._update_channel_model()

    def get_datafile(self, group) -> DataFileController:
        return self._child_map[group]

    @property
    def children(self):
        for i in range(self._segments.rowCount()):
            yield self._segments.child(i)

    def add_child(self, child: LineUpdate) -> DataSegmentController:
        """Add a DataSegment as a child to this DataSet"""

        segment = DataSegment(child.uid, child.start, child.stop,
                              self._segments.rowCount(), label=child.label)
        self.entity.segments.append(segment)
        segment_c = DataSegmentController(segment, self.project, parent=self)
        self._segments.appendRow(segment_c)
        return segment_c

    def remove_child(self, uid: OID, confirm: bool = True):
        # if confirm:
        #     pass
        seg_c: DataSegmentController = self.get_child(uid)
        if seg_c is None:
            raise KeyError("Invalid uid supplied, child does not exist.")

        _log.debug(f'Deleting segment {seg_c} {uid}')
        seg_c.delete()
        self._segments.removeRow(seg_c.row())
        self.entity.segments.remove(seg_c.entity)

    def update(self):
        self.setText(self.entity.name)
        super().update()

    # Context Menu Handlers
    def _action_set_name(self):  # pragma: no cover
        name = controller_helpers.get_input("Set DataSet Name", "Enter a new name:",
                                            self.get_attr('name'),
                                            parent=self.parent_widget)
        if name:
            self.set_attr('name', name)

    def _action_set_sensor_dlg(self):  # pragma: no cover
        sensors = {}
        for i in range(self.project.meter_model.rowCount()):
            sensor = self.project.meter_model.item(i)
            sensors[sensor.text()] = sensor

        item, ok = QInputDialog.getItem(self.parent_widget, "Select Gravimeter",
                                        "Sensor", sensors.keys(), editable=False)
        if ok:
            if self._sensor is not None:
                self.removeRow(self._sensor.row())

            sensor: GravimeterController = sensors[item]
            self.set_attr('sensor', sensor)
            self._sensor: GravimeterController = sensor.clone()
            self.appendRow(self._sensor)

    def _action_delete(self, confirm: bool = True):  # pragma: no cover
        self.get_parent().remove_child(self.uid, confirm)

    def _action_properties(self):  # pragma: no cover
        warnings.warn("Properties action not yet implemented")
