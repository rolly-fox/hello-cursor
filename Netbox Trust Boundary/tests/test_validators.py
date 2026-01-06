"""
Unit tests for validation logic.
"""

import unittest
from core.models import (
    CSVRow,
    ValidationStatus,
    RowClassification,
    NetBoxCache,
    CachedRack,
    CachedDevice,
)
from core.validators import Validator


class TestValidator(unittest.TestCase):
    """Tests for the Validator class."""

    def setUp(self):
        """Set up test fixtures."""
        self.cache = NetBoxCache()
        self.cache.site_id = 1
        self.cache.site_name = "Test Site"
        
        # Add test racks
        rack1 = CachedRack(
            id=1,
            name="ER100-161",
            site_id=1,
            site_name="Test Site",
            u_height=42,
        )
        rack2 = CachedRack(
            id=2,
            name="ER100-162",
            site_id=1,
            site_name="Test Site",
            u_height=42,
        )
        self.cache.add_rack(rack1)
        self.cache.add_rack(rack2)
        
        # Add test device
        device1 = CachedDevice(
            id=1,
            name="EXISTING-DEVICE",
            rack_id=1,
            rack_name="ER100-161",
            position=10,
            u_height=2,
        )
        self.cache.add_device(device1)
        
        self.validator = Validator(self.cache)

    def test_validate_valid_row(self):
        """Test validation of a valid row."""
        row = CSVRow(
            row_number=1,
            rack="ER100-161",
            ru_position=20,
            ru_height=2,
            hostname="NEW-DEVICE",
        )
        
        result = self.validator.validate_row(row)
        
        self.assertEqual(result.status, ValidationStatus.PASS)
        self.assertEqual(result.classification, RowClassification.NETBOX_UPDATE)

    def test_validate_missing_required_fields(self):
        """Test validation fails for missing required fields."""
        row = CSVRow(
            row_number=1,
            rack="",  # Missing rack
            ru_position=None,  # Missing position
            ru_height=2,
        )
        
        result = self.validator.validate_row(row)
        
        self.assertEqual(result.status, ValidationStatus.INVALID)
        self.assertEqual(result.classification, RowClassification.INVALID)
        self.assertTrue(any(i.code == "MISSING_REQUIRED" for i in result.issues))

    def test_validate_rack_not_found(self):
        """Test validation fails for non-existent rack."""
        row = CSVRow(
            row_number=1,
            rack="NONEXISTENT-RACK",
            ru_position=10,
            ru_height=2,
        )
        
        result = self.validator.validate_row(row)
        
        self.assertEqual(result.status, ValidationStatus.FAIL)
        self.assertTrue(any(i.code == "RACK_NOT_FOUND" for i in result.issues))

    def test_validate_ru_collision(self):
        """Test validation detects RU collision."""
        # Device at position 10-11 already exists
        row = CSVRow(
            row_number=1,
            rack="ER100-161",
            ru_position=10,
            ru_height=1,
            hostname="NEW-DEVICE",
        )
        
        result = self.validator.validate_row(row)
        
        self.assertEqual(result.status, ValidationStatus.WARN)
        self.assertTrue(any(i.code == "RU_COLLISION" for i in result.issues))
        self.assertEqual(result.existing_device, "EXISTING-DEVICE")

    def test_validate_ru_out_of_range(self):
        """Test validation fails for RU out of rack bounds."""
        row = CSVRow(
            row_number=1,
            rack="ER100-161",
            ru_position=41,
            ru_height=4,  # Would extend to RU 44, but rack is only 42U
            hostname="NEW-DEVICE",
        )
        
        result = self.validator.validate_row(row)
        
        self.assertEqual(result.status, ValidationStatus.FAIL)
        self.assertTrue(any(i.code == "RU_OUT_OF_RANGE" for i in result.issues))

    def test_validate_device_exists_same_position(self):
        """Test validation recognizes device at same position."""
        row = CSVRow(
            row_number=1,
            rack="ER100-161",
            ru_position=10,
            ru_height=2,
            hostname="EXISTING-DEVICE",  # Same name as existing
        )
        
        result = self.validator.validate_row(row)
        
        # Should be NO_ACTION since device already exists at this position
        self.assertEqual(result.classification, RowClassification.NO_ACTION)

    def test_validate_all_detects_csv_duplicates(self):
        """Test that validate_all detects duplicate positions within CSV."""
        rows = [
            CSVRow(row_number=1, rack="ER100-162", ru_position=20, ru_height=2),
            CSVRow(row_number=2, rack="ER100-162", ru_position=20, ru_height=1),  # Same position
        ]
        
        results = self.validator.validate_all(rows)
        
        # Both should have CSV_COLLISION issue
        self.assertTrue(any(i.code == "CSV_COLLISION" for i in results[0].issues))
        self.assertTrue(any(i.code == "CSV_COLLISION" for i in results[1].issues))


class TestCachedDevice(unittest.TestCase):
    """Tests for CachedDevice model."""

    def test_occupies_ru(self):
        """Test RU occupancy calculation."""
        device = CachedDevice(
            id=1,
            name="Test",
            rack_id=1,
            rack_name="R1",
            position=10,
            u_height=2,
        )
        
        self.assertTrue(device.occupies_ru(10))
        self.assertTrue(device.occupies_ru(11))
        self.assertFalse(device.occupies_ru(9))
        self.assertFalse(device.occupies_ru(12))

    def test_ru_range(self):
        """Test RU range calculation."""
        device = CachedDevice(
            id=1,
            name="Test",
            rack_id=1,
            rack_name="R1",
            position=10,
            u_height=4,
        )
        
        self.assertEqual(device.ru_range, (10, 13))


if __name__ == "__main__":
    unittest.main()
