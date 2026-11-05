"""Transactional append-only candidate store shared by SQLite and MySQL.

Production documents/chunks/knowledge_units are deliberately not mutated here.
Batch withdrawal changes visibility in this data layer, never deletes evidence.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable
from .staging_contracts import canonical_json, content_hash, utc_now, validate_human_review

KINDS = {'source', 'chunk', 'unit', 'qa'}
TABLES = ('webk_batches', 'webk_records', 'webk_batch_records', 'webk_review_events')


def make_record(kind: str, payload: dict) -> dict:
    if kind not in KINDS:
        raise ValueError('unsupported_record_kind')
    digest = content_hash(payload)
    return {'record_id': content_hash({'kind': kind, 'payload_sha256': digest}), 'kind': kind,
            'payload_sha256': digest, 'payload': payload}


class StagingStore:
    def __init__(self, connection, *, dialect: str = 'sqlite'):
        if dialect not in {'sqlite', 'mysql'}:
            raise ValueError('unsupported_dialect')
        self.connection, self.dialect = connection, dialect
        self._placeholder = '?' if dialect == 'sqlite' else '%s'

    @classmethod
    def sqlite(cls, path: str | Path, *, initialize: bool = True):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, timeout=30, isolation_level=None)
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=30000')
        store = cls(conn)
        if initialize:
            store.initialize()
        return store

    def _execute(self, query: str, args: tuple = ()):
        cursor = self.connection.cursor()
        try:
            cursor.execute(query.replace('?', self._placeholder), args)
            rows = cursor.fetchall() if cursor.description else []
            return rows, cursor.rowcount
        finally:
            cursor.close()

    def initialize(self):
        # MySQL DDL commits implicitly. The caller performs the pre-DDL snapshot
        # and opts in separately; data import below remains one transaction.
        text = 'TEXT' if self.dialect == 'sqlite' else 'LONGTEXT'
        suffix = '' if self.dialect == 'sqlite' else ' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4'
        statements = [
            f'''CREATE TABLE IF NOT EXISTS webk_batches (
                batch_id VARCHAR(96) PRIMARY KEY, manifest_sha256 CHAR(64) NOT NULL,
                status VARCHAR(20) NOT NULL, created_at VARCHAR(40) NOT NULL, counts_json {text} NOT NULL)''',
            f'''CREATE TABLE IF NOT EXISTS webk_records (
                record_id CHAR(64) PRIMARY KEY, kind VARCHAR(12) NOT NULL,
                payload_sha256 CHAR(64) NOT NULL, payload_json {text} NOT NULL,
                review_status VARCHAR(24) NOT NULL, created_at VARCHAR(40) NOT NULL)''',
            '''CREATE TABLE IF NOT EXISTS webk_batch_records (
                batch_id VARCHAR(96) NOT NULL, record_id CHAR(64) NOT NULL,
                PRIMARY KEY(batch_id,record_id),
                FOREIGN KEY(batch_id) REFERENCES webk_batches(batch_id),
                FOREIGN KEY(record_id) REFERENCES webk_records(record_id))''',
            f'''CREATE TABLE IF NOT EXISTS webk_review_events (
                event_id CHAR(64) PRIMARY KEY, record_id CHAR(64) NOT NULL,
                previous_status VARCHAR(24) NOT NULL, next_status VARCHAR(24) NOT NULL,
                attestation_json {text} NOT NULL, created_at VARCHAR(40) NOT NULL,
                FOREIGN KEY(record_id) REFERENCES webk_records(record_id))''',
        ]
        for query in statements:
            self._execute(query + suffix)
        self.connection.commit()

    def _begin(self):
        if self.dialect == 'sqlite':
            self.connection.execute('BEGIN IMMEDIATE')
        else:
            self.connection.start_transaction()

    def import_batch(self, batch_id: str, records: Iterable[dict], *, provenance_manifest: dict, fail_after: int | None = None) -> dict:
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', batch_id):
            raise ValueError('invalid_batch_id')
        rows = list(records)
        if len({r['record_id'] for r in rows}) != len(rows):
            raise ValueError('duplicate_record_in_input')
        for row in rows:
            expected = make_record(row['kind'], row['payload'])
            if row != expected:
                raise ValueError('record_identity_mismatch')
            state = row['payload'].get('review_status', 'pending_review')
            if state not in {'machine_draft', 'pending_review'} or row['payload'].get('human_reviewed', False) is not False:
                raise ValueError('import_cannot_grant_human_review')
        manifest_sha = content_hash({'records': sorted(r['record_id'] for r in rows), 'provenance': provenance_manifest})
        counts = {'input': len(rows), 'inserted': 0, 'duplicates': 0, 'updated': 0, 'rejected': 0, 'failed': 0}
        self._begin()
        try:
            old, _ = self._execute('SELECT manifest_sha256,status,counts_json FROM webk_batches WHERE batch_id=?', (batch_id,))
            if old:
                if old[0][0] != manifest_sha:
                    raise ValueError('batch_identity_content_conflict')
                if old[0][1] != 'active':
                    raise ValueError('withdrawn_batch_cannot_be_silently_reactivated')
                stored, _ = self._execute('''SELECT r.record_id,r.kind,r.payload_sha256,r.payload_json
                    FROM webk_records r JOIN webk_batch_records br ON br.record_id=r.record_id WHERE br.batch_id=?''', (batch_id,))
                expected_by_id = {r['record_id']:r for r in rows}
                if len(stored) != len(rows) or any(
                    rid not in expected_by_id or kind != expected_by_id[rid]['kind']
                    or sha != expected_by_id[rid]['payload_sha256'] or content_hash(json.loads(payload)) != sha
                    for rid,kind,sha,payload in stored):
                    raise ValueError('existing_batch_integrity_failed')
                self.connection.rollback()
                return {'batch_id': batch_id, 'status': 'already_imported', 'manifest_sha256': manifest_sha,
                        'counts': {**counts, 'duplicates': len(rows)}, 'original_counts': json.loads(old[0][2])}
            self._execute('INSERT INTO webk_batches VALUES (?,?,?,?,?)', (batch_id, manifest_sha, 'active', utc_now(), '{}'))
            for index, row in enumerate(rows):
                existing, _ = self._execute('SELECT payload_sha256,payload_json FROM webk_records WHERE record_id=?', (row['record_id'],))
                if existing:
                    if existing[0][0] != row['payload_sha256'] or content_hash(json.loads(existing[0][1])) != row['payload_sha256']:
                        raise ValueError('stored_record_hash_conflict')
                    counts['duplicates'] += 1
                else:
                    self._execute('INSERT INTO webk_records VALUES (?,?,?,?,?,?)',
                                  (row['record_id'], row['kind'], row['payload_sha256'], canonical_json(row['payload']), row['payload'].get('review_status', 'pending_review'), utc_now()))
                    counts['inserted'] += 1
                self._execute('INSERT INTO webk_batch_records VALUES (?,?)', (batch_id, row['record_id']))
                if fail_after is not None and index + 1 >= fail_after:
                    raise RuntimeError('injected_import_failure')
            self._execute('UPDATE webk_batches SET counts_json=? WHERE batch_id=?', (canonical_json(counts), batch_id))
            self.connection.commit()
            return {'batch_id': batch_id, 'status': 'imported', 'manifest_sha256': manifest_sha, 'counts': counts}
        except BaseException:
            self.connection.rollback()
            raise

    def withdraw_batch(self, batch_id: str) -> dict:
        self._begin()
        try:
            rows, _ = self._execute('SELECT status FROM webk_batches WHERE batch_id=?', (batch_id,))
            if not rows:
                raise KeyError('unknown_batch')
            self._execute('UPDATE webk_batches SET status=? WHERE batch_id=?', ('withdrawn', batch_id))
            self.connection.commit()
            return {'batch_id': batch_id, 'status': 'withdrawn', 'deleted_records': 0}
        except BaseException:
            self.connection.rollback()
            raise

    def active_records(self, *, kind: str | None = None, include_unreviewed: bool = False) -> list[dict]:
        if kind is not None and kind not in KINDS:
            raise ValueError('unsupported_record_kind')
        query = '''SELECT DISTINCT r.record_id,r.kind,r.payload_json,r.review_status,r.payload_sha256 FROM webk_records r
                   JOIN webk_batch_records br ON br.record_id=r.record_id
                   JOIN webk_batches b ON b.batch_id=br.batch_id WHERE b.status='active' '''
        params = ()
        if kind:
            query += ' AND r.kind=?'
            params = (kind,)
        if not include_unreviewed:
            query += " AND r.review_status IN ('reviewed','published')"
        query += ' ORDER BY r.record_id'
        rows, _ = self._execute(query, params)
        if any(content_hash(json.loads(r[2])) != r[4] for r in rows):
            raise ValueError('stored_record_integrity_failed')
        return [{'record_id': r[0], 'kind': r[1], 'payload': json.loads(r[2]), 'review_status': r[3],
                 'domain_review_attested': r[3] in {'reviewed', 'published'},
                 'reviewer_identity_authenticated': False} for r in rows]

    def record_review(self, record_id: str, attestation: dict) -> dict:
        self._begin()
        try:
            lock = ' FOR UPDATE' if self.dialect == 'mysql' else ''
            rows, _ = self._execute('SELECT payload_json,review_status,kind,payload_sha256 FROM webk_records WHERE record_id=?' + lock, (record_id,))
            if not rows or rows[0][2] != 'unit':
                raise ValueError('unit_record_required')
            candidate, previous = json.loads(rows[0][0]), rows[0][1]
            if content_hash(candidate) != rows[0][3]:
                raise ValueError('stored_record_integrity_failed')
            errors = validate_human_review(attestation, candidate, record_id=record_id)
            if errors:
                raise ValueError(','.join(errors))
            event_id = content_hash({'record_id': record_id, 'attestation': attestation})
            seen, _ = self._execute('SELECT event_id FROM webk_review_events WHERE event_id=?', (event_id,))
            if seen:
                self.connection.rollback()
                return {'event_id': event_id, 'status': 'already_recorded'}
            if previous not in {'machine_draft', 'pending_review'}:
                raise ValueError('reviewed_record_requires_a_new_content_version')
            next_status = 'reviewed' if attestation['decision'] == 'accepted' else 'pending_review'
            self._execute('INSERT INTO webk_review_events VALUES (?,?,?,?,?,?)',
                          (event_id, record_id, previous, next_status, canonical_json(attestation), utc_now()))
            self._execute('UPDATE webk_records SET review_status=? WHERE record_id=?', (next_status, record_id))
            self.connection.commit()
            return {'event_id': event_id, 'status': next_status, 'identity_verified_by_store': False,
                    'note': 'External human attestation recorded; the store does not authenticate a professional identity.'}
        except BaseException:
            self.connection.rollback()
            raise

    def snapshot(self) -> dict:
        result = {}
        if self.dialect == 'mysql':
            self.connection.start_transaction(isolation_level='REPEATABLE READ', consistent_snapshot=True, readonly=True)
        else:
            self.connection.execute('BEGIN')
        try:
            for table in TABLES:
                rows, _ = self._execute(f'SELECT * FROM {table}')
                canonical_rows = sorted([list(r) for r in rows], key=canonical_json)
                result[table] = {'rows': canonical_rows, 'count': len(rows), 'sha256': content_hash(canonical_rows)}
            self.connection.commit()
            return result
        except BaseException:
            self.connection.rollback()
            raise

    @classmethod
    def restore_sqlite_snapshot(cls, path: str | Path, snapshot: dict):
        """Replay an exact snapshot into a new isolated DB; never overwrite a DB."""
        path = Path(path)
        if path.exists() or set(snapshot) != set(TABLES):
            raise ValueError('new_restore_target_and_complete_snapshot_required')
        widths = dict(zip(TABLES,(5,6,2,6)))
        for table in TABLES:
            item=snapshot[table]
            rows=item.get('rows')
            if not isinstance(rows,list) or len(rows)!=item.get('count') or content_hash(rows)!=item.get('sha256') or any(not isinstance(r,list) or len(r)!=widths[table] for r in rows):
                raise ValueError('snapshot_integrity_failed')
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb'):
            pass
        store=cls.sqlite(path)
        try:
            store._begin()
            for table in TABLES:
                for row in snapshot[table]['rows']:
                    store._execute(f"INSERT INTO {table} VALUES ({','.join('?' for _ in row)})",tuple(row))
            store.connection.commit()
            if store.snapshot()!=snapshot:
                raise ValueError('restored_snapshot_differs')
            return store
        except BaseException:
            store.connection.rollback()
            store.close()
            raise

    def publish_units(self, record_ids: list[str], *, release: dict) -> dict:
        """Publish already reviewed unit versions after an external release decision.

        This changes only this data layer. It cannot activate a retrieval index.
        An operator remains responsible for authenticating the human sign-off.
        """
        if not record_ids or len(record_ids) != len(set(record_ids)):
            raise ValueError('unique_nonempty_record_ids_required')
        if (release.get('origin') != 'human'
                or not all(isinstance(release.get(k),str) and release[k].strip() for k in ('publisher','rationale'))
                or release.get('record_ids') != sorted(record_ids)
                or release.get('domain_review_verified') is not True
                or release.get('source_license_rechecked') is not True):
            raise ValueError('external_content_bound_release_required')
        self._begin()
        try:
            updates = []
            for record_id in sorted(record_ids):
                lock = ' FOR UPDATE' if self.dialect == 'mysql' else ''
                rows, _ = self._execute('SELECT payload_json,review_status,kind,payload_sha256 FROM webk_records WHERE record_id=?' + lock, (record_id,))
                if not rows or rows[0][2] != 'unit' or rows[0][1] not in {'reviewed','published'}:
                    raise ValueError('every_published_unit_requires_prior_human_review')
                if content_hash(json.loads(rows[0][0])) != rows[0][3]:
                    raise ValueError('stored_record_integrity_failed')
                active, _ = self._execute('''SELECT br.batch_id FROM webk_batch_records br JOIN webk_batches b
                    ON b.batch_id=br.batch_id WHERE br.record_id=? AND b.status='active' ''', (record_id,))
                if not active:
                    raise ValueError('cannot_publish_withdrawn_evidence')
                event_id = content_hash({'record_id': record_id, 'release': release})
                event, _ = self._execute('SELECT event_id FROM webk_review_events WHERE event_id=?', (event_id,))
                if event:
                    continue
                if rows[0][1] == 'published':
                    raise ValueError('already_published_with_different_release')
                updates.append((record_id, event_id))
            for record_id, event_id in updates:
                self._execute('INSERT INTO webk_review_events VALUES (?,?,?,?,?,?)',
                    (event_id, record_id, 'reviewed', 'published', canonical_json({'event_type':'release','release':release}), utc_now()))
                self._execute('UPDATE webk_records SET review_status=? WHERE record_id=?', ('published',record_id))
            self.connection.commit()
            return {'status':'published', 'updated':len(updates), 'index_activated':False,
                    'publisher_identity_authenticated':False}
        except BaseException:
            self.connection.rollback()
            raise

    def close(self):
        self.connection.close()
