import json
import struct
import unittest

from backend.database.recover_observations import clustered_rows, same_record, sql_values


class ObservationRecoveryTests(unittest.TestCase):
    def page(self):
        page = bytearray(16384)
        offset = 129
        features = json.dumps({'observed_delay_ms': 42.5, 'note': 'x' * 160})
        data = (struct.pack('>I', 2**31 + 4388) + bytes(13) + struct.pack('>I', 2**31 + 1)
                + b'GND-001' + struct.pack('>I', 2**31 + 229) + b'online'
                + features.encode() + struct.pack('<f', 26.851139068603516))
        page[offset:offset+len(data)] = data
        page[97:99] = struct.pack('>H', offset - 99)
        page[offset-2:offset] = struct.pack('>H', (112-offset) % 16384)
        page[offset-6] = 7
        page[offset-7] = 6
        page[offset-8] = 0x80 | (len(features) >> 8)
        page[offset-9] = len(features) & 255
        page[54:56] = struct.pack('>H', 1)
        return page, offset, features

    def test_compact_leaf_preserves_identifiers_json_and_float(self):
        page, _, features = self.page()
        rows = list(clustered_rows(page, 132))
        self.assertEqual(rows[0][0], (4388, 1, 'GND-001', 229, 'online', features, 26.851139068603516))
        self.assertEqual(rows[0][1], 'ibd:132:129')

    def test_external_json_and_delete_marks_fail_closed(self):
        for index, flag in ((-8, 0x40), (-5, 0x20)):
            page, offset, _ = self.page()
            page[offset+index] |= flag
            with self.assertRaises(ValueError):
                list(clustered_rows(page, 132))

    def test_broken_chain_and_record_count_are_rejected(self):
        page, offset, _ = self.page()
        page[offset-2:offset] = b'\0\0'
        with self.assertRaisesRegex(ValueError, 'record chain'):
            list(clustered_rows(page, 132))
        page, _, _ = self.page()
        page[54:56] = struct.pack('>H', 2)
        with self.assertRaisesRegex(ValueError, 'count mismatch'):
            list(clustered_rows(page, 132))

    def test_sql_dump_is_decoded_as_data_without_execution(self):
        values = list(sql_values("(1,1,'GND-001',0,'train','{\\\"note\\\":\\\"quoted \\\' value\\\"}',26.8511);"))
        self.assertEqual(values[0][:5], [1, 1, 'GND-001', 0, 'train'])
        self.assertEqual(json.loads(values[0][5]), {'note': "quoted ' value"})

    def test_backup_rounding_is_allowed_but_conflicting_data_is_rejected(self):
        row = (1, 1, 'GND-001', 0, 'train', '{"x":1}', 26.851139068603516)
        backup = (*row[:6], 26.8511)
        self.assertTrue(same_record(row, backup))
        self.assertFalse(same_record(row, (*row[:6], 26.852)))
        self.assertFalse(same_record(row, (*row[:5], '{"x":2}', row[6])))
