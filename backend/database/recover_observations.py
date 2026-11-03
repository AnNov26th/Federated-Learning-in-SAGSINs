"""Extract original observation records to a local candidate; never edits MySQL.

Supports this project's uncompressed COMPACT clustered leaf pages and SQL dumps.
Unknown layouts, external JSON fields, duplicates or conflicting backups fail closed.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import struct

PAGE_SIZE = 16384
COLUMNS = ('id', 'dataset_id', 'client_id', 'sequence', 'split', 'features_json', 'target_delay_ms')


def signed_integer(value):
    return struct.unpack('>I', value)[0] - 2**31


def clustered_rows(page, page_number):
    """Walk the live record list, ignoring heap garbage and delete-marked records."""
    offset, visited = 99, set()  # COMPACT infimum record.
    while True:
        offset = (offset + struct.unpack('>H', page[offset-2:offset])[0]) % PAGE_SIZE
        if offset == 112:  # supremum
            break
        if offset in visited or not 120 <= offset < PAGE_SIZE - 8:
            raise ValueError(f'Broken record chain at page {page_number}')
        visited.add(offset)
        if page[offset-5] & 0x20:
            raise ValueError('Delete-marked record needs MVCC recovery, not this extractor')
        client_size, split_size, size = page[offset-6], page[offset-7], page[offset-8]
        if size & 0x80:
            if size & 0x40:
                raise ValueError('Externally stored JSON is unsupported')
            size = ((size & 0x3f) << 8) | page[offset-9]
        identifier = signed_integer(page[offset:offset+4])
        position = offset + 17  # PK plus DB_TRX_ID and DB_ROLL_PTR.
        dataset = signed_integer(page[position:position+4]); position += 4
        client = page[position:position+client_size].decode('utf-8'); position += client_size
        sequence = signed_integer(page[position:position+4]); position += 4
        split = page[position:position+split_size].decode('utf-8'); position += split_size
        features = page[position:position+size].decode('utf-8'); position += size
        if position + 4 > PAGE_SIZE - 8:
            raise ValueError('Record extends past page data')
        target = struct.unpack('<f', page[position:position+4])[0]
        if identifier < 1 or dataset < 1 or sequence < 0 or not client or \
                split not in ('train', 'validation', 'online', 'test') or \
                not math.isfinite(target) or target < 0 or not isinstance(json.loads(features), dict):
            raise ValueError(f'Invalid record on page {page_number}')
        yield (identifier, dataset, client, sequence, split, features, target), f'ibd:{page_number}:{offset}'
    if len(visited) != struct.unpack('>H', page[54:56])[0]:
        raise ValueError(f'Record count mismatch on page {page_number}')


def sql_values(body):
    """Decode MySQL dump values without executing any SQL."""
    position = 0
    escapes = {'0': '\0', 'n': '\n', 'r': '\r', 't': '\t', 'b': '\b', 'Z': '\x1a'}
    while position < len(body):
        while position < len(body) and body[position] in ' ,\r\n;':
            position += 1
        if position == len(body):
            return
        if body[position] != '(':
            raise ValueError('Invalid SQL tuple')
        position += 1
        values = []
        while True:
            if body[position] == "'":
                position += 1
                chars = []
                while True:
                    char = body[position]; position += 1
                    if char == '\\':
                        char = body[position]; position += 1
                        chars.append(escapes.get(char, char))
                    elif char == "'":
                        break
                    else:
                        chars.append(char)
                value = ''.join(chars)
            else:
                start = position
                while body[position] not in ',)':
                    position += 1
                token = body[start:position]
                value = None if token == 'NULL' else float(token) if any(x in token.lower() for x in '.e') else int(token)
            values.append(value)
            delimiter = body[position]; position += 1
            if delimiter == ')':
                break
            if delimiter != ',':
                raise ValueError('Invalid SQL delimiter')
        yield values


def same_record(a, b):
    return tuple(a[:5]) == tuple(b[:5]) and json.loads(a[5]) == json.loads(b[5]) and \
        (struct.pack('<f', a[6]) == struct.pack('<f', b[6]) or
         float(format(a[6], '.6g')) == b[6])


def extract(ibd, backup, output, space_id=16, index_id=51):
    if output.exists():
        raise ValueError('Refusing to overwrite a recovery candidate')
    if ibd.stat().st_size % PAGE_SIZE:
        raise ValueError('Unexpected tablespace page size')
    output.parent.mkdir(parents=True, exist_ok=True)
    sources = Counter()
    overlapping = 0
    with sqlite3.connect(output) as db:
        db.execute('CREATE TABLE observations (id INTEGER PRIMARY KEY, dataset_id INTEGER NOT NULL, '
                   'client_id TEXT NOT NULL, sequence INTEGER NOT NULL, split TEXT NOT NULL, '
                   'features_json TEXT NOT NULL, target_delay_ms REAL NOT NULL, origin TEXT NOT NULL, '
                   'UNIQUE(dataset_id,client_id,sequence))')
        with ibd.open('rb') as stream:
            for number in range(ibd.stat().st_size // PAGE_SIZE):
                page = stream.read(PAGE_SIZE)
                if struct.unpack('>I', page[34:38])[0] != space_id or \
                        struct.unpack('>H', page[24:26])[0] != 17855 or \
                        struct.unpack('>H', page[64:66])[0] != 0 or \
                        struct.unpack('>Q', page[66:74])[0] != index_id:
                    continue
                if struct.unpack('>I', page[4:8])[0] != number:
                    raise ValueError('Mismatched physical page number')
                for row, origin in clustered_rows(page, number):
                    db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)', (*row, origin))
                    sources['ibd'] += 1
        # Dumps contain one complete INSERT statement per line, with escaped strings.
        with backup.open(encoding='utf-8') as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.startswith('INSERT INTO `network_observations` VALUES '):
                    continue
                for row in sql_values(line.split(' VALUES ', 1)[1]):
                    if len(row) != 7:
                        raise ValueError('Unexpected SQL schema')
                    original = db.execute('SELECT ' + ','.join(COLUMNS) + ' FROM observations WHERE id=?', (row[0],)).fetchone()
                    if original:
                        if not same_record(original, row):
                            raise ValueError(f'Backup conflicts with physical record {row[0]}')
                        overlapping += 1
                    else:
                        row[6] = struct.unpack('<f', struct.pack('<f', row[6]))[0]
                        db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?)',
                                   (*row, f'sql:{line_number}'))
                        sources['sql'] += 1
        if not sources['ibd'] or not sources['sql'] or not overlapping:
            raise ValueError('Missing physical or backup overlap evidence')
        summary = dict(complete=True, sources=dict(sources), matching_backup_records=overlapping,
                       backup_float_precision='MySQL dump FLOAT values rounded to six significant digits; physical rows retain full float32 precision',
                       dataset_counts=dict(db.execute('SELECT dataset_id,COUNT(*) FROM observations GROUP BY dataset_id')),
                       rows=db.execute('SELECT COUNT(*) FROM observations').fetchone()[0],
                       min_id=db.execute('SELECT MIN(id) FROM observations').fetchone()[0],
                       max_id=db.execute('SELECT MAX(id) FROM observations').fetchone()[0],
                       input_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ibd, backup)})
    output.with_suffix('.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ibd', required=True, type=Path)
    parser.add_argument('--backup', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(extract(args.ibd, args.backup, args.output), indent=2))


if __name__ == '__main__':
    main()
