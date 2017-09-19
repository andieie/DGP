# coding: utf-8

"""Provide definitions of the models used by the Qt Application in our model/view widgets."""

from PyQt5 import QtCore


class TableModel(QtCore.QAbstractTableModel):
    """Simple table model of key: value pairs."""

    def __init__(self, columns, editable=None, parent=None):
        super().__init__(parent=parent)
        # TODO: Allow specification of which columns are editable
        # List of column headers
        self._cols = columns
        self._editable = editable
        # A list of 2-tuples (key: value pairs) which will be the table rows
        self._rows = []
        self._updates = {}

    def set_object(self, obj):
        """Populates the model with key, value pairs from the passed objects' __dict__"""
        for key, value in obj.__dict__.items():
            self.append(key, value)

    def append(self, *args):
        """Add a new row of data to the table, trimming input array to length of columns."""
        self._rows.append(args[:len(self._cols)])
        return True

    @property
    def updates(self):
        return self._updates

    @property
    def data(self):
        # TODO: Work on some sort of mapping to map column headers to row values
        return self._rows

    # Required implementations of super class (for a basic, non-editable table)

    def rowCount(self, parent=None, *args, **kwargs):
        return len(self._rows)

    def columnCount(self, parent=None, *args, **kwargs):
        return len(self._cols)

    def data(self, index: QtCore.QModelIndex, role=None):
        if role == QtCore.Qt.DisplayRole:
            try:
                return self._rows[index.row()][index.column()]
            except IndexError:
                return None
        return QtCore.QVariant()

    def flags(self, index: QtCore.QModelIndex):
        flags = QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled
        if index.column() in self._editable:  # Allow the values column to be edited
            flags = flags | QtCore.Qt.ItemIsEditable
        return flags

    def headerData(self, section, orientation, role=None):
        if role == QtCore.Qt.DisplayRole and orientation == QtCore.Qt.Horizontal:
            return self._cols[section]

    # Required implementations of super class for editable table

    def setData(self, index: QtCore.QModelIndex, value: QtCore.QVariant, role=None):
        """Basic implementation of editable model. This doesn't propagate the changes to the underlying
        object upon which the model was based though (yet)"""
        if index.isValid() and role == QtCore.Qt.ItemIsEditable:
            old_data = self._rows[index.row()]
            print("Setting value of item at {}:{} to {}".format(index.row(), index.column(), value))
            new_data = old_data[0], str(value)
            self._rows[index.row()] = new_data
            self._updates[self._rows[index.row()][0]] = self._rows[index.row()][index.column()]

            self.dataChanged.emit(index, index)
            return True
        else:
            return False
