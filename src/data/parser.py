from __future__ import annotations

import sqlite3
from pathlib import Path

from rich.console import Console

console = Console()


class WeChatDBParser:
    def __init__(self, db_dir: str) -> None:
        self.set_db_dir(db_dir)

    def set_db_dir(self, db_dir: str) -> None:
        """(Re-)point the parser at a database directory, auto-detecting layout."""
        self.db_dir = Path(db_dir)
        self._detect_layout()

    def _detect_layout(self) -> None:
        """Auto-detect whether DBs are in sub-folders or flat in the root."""
        d = self.db_dir

        nested_contact = d / "contact" / "contact.db"
        nested_messages = sorted(d.glob("message/message_*.db"))

        if nested_contact.exists() or nested_messages:
            self.contact_db = nested_contact
            self.message_dbs = [f for f in nested_messages if "_fts" not in f.name and "_resource" not in f.name]
        else:
            all_dbs = sorted(d.rglob("*.db"))
            self.contact_db = next((f for f in all_dbs if "contact" in f.name and "fts" not in f.name), d / "contact.db")
            self.message_dbs = [f for f in all_dbs if "message" in f.name and "_fts" not in f.name and "_resource" not in f.name]

        console.print(f"[bold]数据库目录:[/bold] {self.db_dir}")
        console.print(f"[bold]联系人数据库:[/bold] {'✓' if self.contact_db.exists() else '✗'}")
        console.print(f"[bold]消息数据库:[/bold] {len(self.message_dbs)} 个文件")

    def _query_db(self, db_path: Path, sql: str, params: tuple = ()) -> list[dict]:
        if not db_path.exists():
            return []
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
            rows = [dict(row) for row in cursor.fetchall()]
            conn.close()
            return rows
        except sqlite3.OperationalError as e:
            console.print(f"[red]查询失败 {db_path.name}: {e}[/red]")
            return []

    def _get_table_names(self, db_path: Path) -> list[str]:
        if not db_path.exists():
            return []
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            names = [row[0] for row in cursor.fetchall()]
            conn.close()
            return names
        except sqlite3.OperationalError:
            return []

    def _get_msg_tables(self, db_path: Path) -> list[str]:
        """Get all Msg_<hash> tables (WeChat 4.x) or legacy 'message' table."""
        tables = self._get_table_names(db_path)
        msg_tables = [t for t in tables if t.startswith("Msg_")]
        if msg_tables:
            return msg_tables
        if "message" in tables:
            return ["message"]
        return []

    def _get_name2id(self, db_path: Path) -> dict:
        """Read Name2Id table to map row-index to wxid."""
        rows = self._query_db(db_path, "SELECT rowid, user_name FROM Name2Id")
        return {r["rowid"]: r["user_name"] for r in rows}

    def get_contacts(self) -> list[dict]:
        tables = self._get_table_names(self.contact_db)

        # WeChat 4.x: 'contact' table with wcId/nickName/remark
        if "contact" in tables:
            rows = self._query_db(self.contact_db, "SELECT * FROM contact LIMIT 1")
            if rows:
                sample = rows[0]
                if "wcId" in sample:
                    contacts = self._query_db(
                        self.contact_db,
                        "SELECT wcId AS UserName, nickName AS NickName, remark AS Remark FROM contact",
                    )
                elif "UserName" in sample:
                    contacts = self._query_db(
                        self.contact_db,
                        "SELECT UserName, NickName, Remark FROM contact",
                    )
                elif "username" in sample:
                    contacts = self._query_db(
                        self.contact_db,
                        "SELECT username AS UserName, nick_name AS NickName, remark AS Remark FROM contact",
                    )
                else:
                    contacts = self._query_db(self.contact_db, "SELECT * FROM contact")
                console.print(f"[green]读取联系人: {len(contacts)} 条[/green]")
                return contacts
        return []

    def _build_hash_to_wxid(self, db_path: Path) -> dict:
        """Map table hash (md5 of wxid) to wxid using Name2Id."""
        import hashlib
        name2id = self._get_name2id(db_path)
        mapping = {}
        for _, wxid in name2id.items():
            if wxid:
                h = hashlib.md5(wxid.encode()).hexdigest()
                mapping[h] = wxid
        return mapping

    def _build_partner_id_per_table(self, db_path: Path) -> dict[str, set[int]]:
        """For each Msg_<hash> table, determine which sender_id(s) are the PARTNER.

        Table hash = md5(partner_wxid). Look up the partner's rowid in Name2Id.
        Returns {table_name: {partner_sender_ids}}.
        """
        import hashlib
        name2id = self._get_name2id(db_path)
        wxid_to_rowids: dict[str, set[int]] = {}
        for rowid, wxid in name2id.items():
            wxid_to_rowids.setdefault(wxid, set()).add(rowid)

        msg_tables = self._get_msg_tables(db_path)
        result: dict[str, set[int]] = {}

        for table in msg_tables:
            table_hash = table.replace("Msg_", "")
            partner_wxid = None
            for wxid, rowids in wxid_to_rowids.items():
                if wxid and hashlib.md5(wxid.encode()).hexdigest() == table_hash:
                    partner_wxid = wxid
                    break
            if partner_wxid:
                result[table] = wxid_to_rowids.get(partner_wxid, set())

        return result

    def _detect_self_rowids(self, db_path: Path) -> set[int]:
        """Detect the user's own rowid(s) in this DB by cross-referencing 1:1 chat tables.

        In a 1:1 chat, the table hash = md5(partner_wxid). The sender_id that is NOT
        the partner must be self. The wxid appearing most frequently as "self" across
        all 1:1 tables is the user.
        """
        import sqlite3 as _sql
        from collections import Counter

        name2id = self._get_name2id(db_path)
        hash_to_wxid = self._build_hash_to_wxid(db_path)
        partner_ids_per_table = self._build_partner_id_per_table(db_path)

        self_wxid_votes: Counter[str] = Counter()

        for table, partner_ids in partner_ids_per_table.items():
            talker = hash_to_wxid.get(table.replace("Msg_", ""), "")
            if "@chatroom" in talker or not partner_ids:
                continue
            try:
                conn = _sql.connect(str(db_path))
                distinct = conn.execute(
                    'SELECT DISTINCT real_sender_id FROM "{}"'.format(table)
                ).fetchall()
                conn.close()
            except Exception:
                continue

            for (sid,) in distinct:
                if sid not in partner_ids:
                    wxid = name2id.get(sid, "")
                    if wxid:
                        self_wxid_votes[wxid] += 1

        if not self_wxid_votes:
            return set()

        user_wxid = self_wxid_votes.most_common(1)[0][0]
        return {rowid for rowid, wxid in name2id.items() if wxid == user_wxid}

    def _read_messages_v4(self, db_path: Path, text_only: bool = False,
                          contact_wxid: str | None = None) -> list[dict]:
        """Read messages from WeChat 4.x Msg_<hash> tables, normalizing to legacy format."""
        msg_tables = self._get_msg_tables(db_path)
        if not msg_tables:
            return []

        hash_to_wxid = self._build_hash_to_wxid(db_path)
        partner_ids_per_table = self._build_partner_id_per_table(db_path)
        self_rowids = self._detect_self_rowids(db_path)
        all_rows = []

        for table in msg_tables:
            try:
                conn = sqlite3.connect(str(db_path))
                col_info = conn.execute('PRAGMA table_info("{}")'.format(table)).fetchall()
                col_names = {c[1] for c in col_info}
                conn.close()
            except Exception:
                col_names = set()

            is_v4 = "message_content" in col_names and "local_type" in col_names

            if is_v4:
                table_hash = table.replace("Msg_", "")
                talker = hash_to_wxid.get(table_hash, table_hash)

                if contact_wxid and talker != contact_wxid:
                    continue

                is_chatroom = "@chatroom" in talker

                where_parts = []
                if text_only:
                    where_parts.append("local_type = 1")
                where_clause = " AND ".join(where_parts) if where_parts else "1=1"

                sql = (
                    'SELECT server_id, local_type, real_sender_id, create_time, message_content '
                    'FROM "{}" WHERE {}'
                ).format(table, where_clause)

                partner_ids = partner_ids_per_table.get(table, set())
                rows = self._query_db(db_path, sql)
                for r in rows:
                    sender_id = r.get("real_sender_id") or 0
                    if sender_id == 0:
                        is_self = False
                    elif is_chatroom:
                        is_self = sender_id in self_rowids
                    elif partner_ids:
                        is_self = sender_id not in partner_ids
                    else:
                        is_self = sender_id in self_rowids if self_rowids else False
                    all_rows.append({
                        "MsgSvrID": r.get("server_id", 0),
                        "type": r.get("local_type", 0),
                        "IsSender": 1 if is_self else 0,
                        "StrTalker": talker,
                        "StrContent": r.get("message_content", "") or "",
                        "CreateTime": r.get("create_time", 0),
                    })
            else:
                # Legacy format
                where_parts = []
                if text_only:
                    where_parts.append("type = 1")
                if contact_wxid:
                    where_parts.append("StrTalker = ?")
                where_clause = " AND ".join(where_parts) if where_parts else "1=1"
                params_tuple = (contact_wxid,) if contact_wxid else ()
                sql = (
                    'SELECT MsgSvrID, type, IsSender, StrTalker, StrContent, CreateTime '
                    'FROM "{}" WHERE {}'
                ).format(table, where_clause)
                rows = self._query_db(db_path, sql, params_tuple)
                all_rows.extend(rows)

        return all_rows

    def get_messages(self, contact_wxid: str | None = None) -> list[dict]:
        all_messages = []
        for db_path in self.message_dbs:
            all_messages.extend(self._read_messages_v4(db_path, text_only=False, contact_wxid=contact_wxid))
        all_messages.sort(key=lambda m: m.get("CreateTime", 0))
        return all_messages

    def get_all_text_messages(self) -> list[dict]:
        all_messages = []
        for db_path in self.message_dbs:
            all_messages.extend(self._read_messages_v4(db_path, text_only=True))
        all_messages.sort(key=lambda m: m.get("CreateTime", 0))
        console.print(f"[green]读取文本消息: {len(all_messages)} 条[/green]")
        return all_messages

    def get_stats(self) -> dict:
        """Return summary statistics about the loaded data."""
        contacts = self.get_contacts()
        messages = self.get_all_text_messages()

        if not messages:
            return {"total_messages": 0, "total_contacts": len(contacts)}

        from collections import Counter
        from datetime import datetime, timezone

        senders = Counter(m.get("StrTalker", "") for m in messages)
        sent = sum(1 for m in messages if m.get("IsSender") == 1)
        received = len(messages) - sent
        timestamps = [m.get("CreateTime", 0) for m in messages if m.get("CreateTime")]

        top_contacts = senders.most_common(20)
        try:
            contacts_db = self.get_contacts()
            name_map = {}
            for c in contacts_db:
                wxid = c.get("UserName", "")
                name = c.get("Remark") or c.get("NickName") or wxid
                if wxid:
                    name_map[wxid] = name
            top_contacts_named = [
                (name_map.get(wxid, wxid), count) for wxid, count in top_contacts
            ]
        except Exception:
            top_contacts_named = top_contacts

        monthly = Counter()  # type: Counter
        hourly = Counter()  # type: Counter
        for ts in timestamps:
            try:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                monthly[dt.strftime("%Y-%m")] += 1
                hourly[dt.hour] += 1
            except (OSError, ValueError):
                pass

        start = datetime.fromtimestamp(min(timestamps), tz=timezone.utc).strftime("%Y-%m-%d") if timestamps else ""
        end = datetime.fromtimestamp(max(timestamps), tz=timezone.utc).strftime("%Y-%m-%d") if timestamps else ""

        return {
            "total_messages": len(messages),
            "total_contacts": len(contacts),
            "unique_talkers": len(senders),
            "sent": sent,
            "received": received,
            "date_start": start,
            "date_end": end,
            "top_contacts": top_contacts,
            "top_contacts_named": top_contacts_named,
            "monthly_distribution": dict(sorted(monthly.items())),
            "hourly_distribution": {h: hourly.get(h, 0) for h in range(24)},
        }
