# coding: utf-8

import unittest
import random
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from .context import dgp
from dgp.lib.project import *
from dgp.lib.meterconfig import *


class TestProject(unittest.TestCase):

    def setUp(self):
        """Set up some dummy classes for testing use"""
        self.todelete = []
        self.project = AirborneProject(path=Path('./tests'),
                                       name='Test Airborne Project')

        # Sample values for testing meter configs
        self.meter_vals = {
            'gravcal': random.randint(200000, 300000),
            'longcal': random.uniform(150.0, 250.0),
            'crosscal': random.uniform(150.0, 250.0),
            'cross_lead': random.random()
        }
        self.at1a5 = MeterConfig(name="AT1A-5", **self.meter_vals)
        self.project.add_meter(self.at1a5)

    def test_project_directory(self):
        """
        Test the handling of the directory specifications within a project
        Project should take an existing directory as a path, raising
        FileNotFoundError if it doesnt exist.
        If the path exists but is a file, Project should automatically strip the
        leaf and use the parent path.
        """
        with self.assertRaises(FileNotFoundError):
            project = GravityProject(path=Path('tests/invalid_dir'),
                                     name='Test')

        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            project = GravityProject(path=project_dir, name='Test')
            self.assertEqual(project.projectdir, project_dir)

        # Test exception given a file instead of directory
        with tempfile.NamedTemporaryFile() as tf:
            tf.write(b"This is not a directory")
            with self.assertRaises(NotADirectoryError):
                project = GravityProject(path=Path(str(tf.name)), name='Test')

    def test_pickle_project(self):
        # TODO: Add further complexity to testing of project pickling
        flight = Flight(self.project, 'test_flight', self.at1a5)
        line = FlightLine(0, 1, 0, None)
        flight.add_line(line)
        self.project.add_flight(flight)

        with tempfile.TemporaryDirectory() as td:
            save_loc = Path(td, 'project.d2p')
            self.project.save(save_loc)

            loaded_project = AirborneProject.load(save_loc)
            self.assertIsInstance(loaded_project, AirborneProject)
            self.assertEqual(len(list(loaded_project.flights)), 1)
            self.assertEqual(loaded_project.get_flight(flight.uid).uid,
                             flight.uid)
            self.assertEqual(loaded_project.get_flight(flight.uid).meter.name,
                             'AT1A-5')


class TestFlight(unittest.TestCase):
    def setUp(self):
        self._trj_data_path = 'tests/sample_data/eotvos_short_input.txt'
        hour = timedelta(hours=1)
        self._line0 = FlightLine(datetime.now(), datetime.now()+hour)
        self._line1 = FlightLine(datetime.now(), datetime.now()+hour+hour)
        self.lines = [self._line0, self._line1]
        self.flight = Flight(None, 'TestFlight', None)

    def test_flight_init(self):
        """Test initialization properties of a new Flight"""
        with tempfile.TemporaryDirectory() as td:
            project_dir = Path(td)
            project = AirborneProject(path=project_dir, name='TestFlightPrj')
            flt = Flight(project, 'Flight1')
            assert flt.channels == []
            self.assertEqual(len(flt), 0)

    def test_line_manipulation(self):
        l0 = self.flight.add_line(self._line0)
        self.assertEqual(0, l0)
        self.flight.remove_line(self._line0.uid)
        self.assertEqual(0, len(self.flight))

        l1 = self.flight.add_line(self._line1)
        self.assertEqual(1, l1)
        l2 = self.flight.add_line(self._line0)
        self.assertEqual(2, l2)
        self.assertEqual(2, len(self.flight))

    def test_flight_iteration(self):
        l0 = self.flight.add_line(self._line0)
        l1 = self.flight.add_line(self._line1)
        # Test sequence numbers
        self.assertEqual(0, l0)
        self.assertEqual(1, l1)

        for line in self.flight.lines:
            self.assertTrue(line in self.lines)

        for line in self.flight:
            self.assertTrue(line in self.lines)


class TestMeterconfig(unittest.TestCase):
    def setUp(self):
        self.ini_path = os.path.abspath('tests/at1m.ini')
        self.config = {
            'g0': 10000.0,
            'GravCal': 227626.0,
            'LongCal': 200.0,
            'CrossCal': 200.1,
            'vcc': 0.0,
            've': 0.0,
            'Cross_Damping': 550.0,
            'Long_Damping': 550.0,
            'at1_invalid': 12345.8
        }

    def test_MeterConfig(self):
        mc = MeterConfig(name='Test-1', **self.config)
        self.assertEqual(mc.name, 'Test-1')

        # Test get, set and len methods of the MeterConfig class
        self.assertEqual(len(mc), len(self.config))

        for k in self.config.keys():
            self.assertEqual(mc[k], self.config[k])
            # Test case-insensitive handling
            self.assertEqual(mc[k.lower()], self.config[k])

        mc['g0'] = 500.01
        self.assertEqual(mc['g0'], 500.01)
        self.assertIsInstance(mc['g0'], float)
        # Test the setting of non-float types
        mc['monitor'] = True
        self.assertTrue(mc['monitor'])

        mc['str_val'] = 'a string'
        self.assertEqual(mc['str_val'], 'a string')

        # Test the class handling of invalid requests/types
        with self.assertRaises(NotImplementedError):
            mc[0: 3]

        with self.assertRaises(NotImplementedError):
            MeterConfig.from_ini(self.ini_path)

    def test_AT1Meter_config(self):
        at1 = AT1Meter('AT1M-5', **self.config)

        self.assertEqual(at1.name, 'AT1M-5')

        # Test that invalid field was not set
        self.assertIsNone(at1['at1_invalid'])
        valid_fields = {k: v for k, v in self.config.items() if k != 'at1_invalid'}
        for k in valid_fields.keys():
            # Check all valid fields were set
            self.assertEqual(at1[k], valid_fields[k])

    def test_AT1Meter_from_ini(self):
        at1 = AT1Meter.from_ini(self.ini_path)

        # Check type inheritance
        self.assertIsInstance(at1, AT1Meter)
        self.assertIsInstance(at1, MeterConfig)

        self.assertEqual(at1.name, 'AT1M-1U')

        cfp = configparser.ConfigParser(strict=False)  # strict=False to allow for duplicate keys in config
        cfp.read(self.ini_path)

        skip_fields = ['meter', '00gravcal']
        for k, v in cfp['Sensor'].items():
            if k in skip_fields:
                continue
            self.assertEqual(float(cfp['Sensor'][k]), at1[k])



