from __future__ import annotations
import math
import os
import sqlite3
import tempfile
import time
from contextlib import closing
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from threading import RLock
from zoneinfo import ZoneInfo
from domain.measurements import resolve_unit

TEHRAN = ZoneInfo("Asia/Tehran")


class LocalDeliveryFile:
    def __init__(self, directory: Path, *, refresh_seconds: float = 60, sources=()) -> None:
        if not math.isfinite(refresh_seconds) or refresh_seconds < 0:
            raise ValueError("refresh_seconds must be finite and non-negative.")
        self._sources = {camera["camera_code"]: camera.get("description") or camera.get("name") or camera["camera_code"] for camera in sources}
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database_path = self.directory / "records.sqlite3"
        self._refresh_seconds = refresh_seconds
        self._last_refresh = -math.inf
        self._lock = RLock()
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS records (
                    event_id TEXT PRIMARY KEY, day TEXT NOT NULL, camera_code TEXT NOT NULL,
                    name TEXT NOT NULL, description TEXT NOT NULL, unit TEXT NOT NULL,
                    raw_value INTEGER NOT NULL, captured_at TEXT NOT NULL, recorded_at TEXT NOT NULL
                )""")
                connection.execute("CREATE INDEX IF NOT EXISTS ix_records_day_camera ON records(day, camera_code)")
            self._dirty = {row[0] for row in connection.execute("SELECT DISTINCT day FROM records")}
            self._dirty.add(datetime.now(TEHRAN).date().isoformat())

    def record(self, event) -> None:
        captured_at = event["scheduled_at"]
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        captured_at = captured_at.astimezone(TEHRAN)
        day = captured_at.date().isoformat()
        code = event["camera_code"]
        source = event.get("source", {})
        data = event["erp_data"]
        unit = resolve_unit(code, source.get("unit") or None)
        with self._lock:
            with closing(sqlite3.connect(self.database_path)) as connection:
                with connection:
                    connection.execute("""INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(event_id) DO NOTHING""", (
                        event["event_id"], day, code, source.get("name") or code,
                        str(data["RecordType"]), unit, data["Temperature"],
                        captured_at.isoformat(timespec="milliseconds"),
                        datetime.now(TEHRAN).isoformat(timespec="milliseconds"),
                    ))
            self._dirty.add(day)
            self.flush()

    def flush(self, *, force: bool = False) -> None:
        with self._lock:
            if not force and time.monotonic() - self._last_refresh < self._refresh_seconds:
                return
            for day in sorted(self._dirty):
                self._write_report(day)
                self._dirty.remove(day)
            self._last_refresh = time.monotonic()

    def _write_report(self, day: str) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            rows = connection.execute("""SELECT camera_code, name, description, unit, raw_value,
                captured_at, recorded_at, event_id FROM records WHERE day = ?
                ORDER BY captured_at, event_id""", (day,)).fetchall()
        counts = {code: [name, 0, 0, 0] for code, name in self._sources.items()}
        detail = []
        for number, (code, name, description, unit, value, captured, recorded, identifier) in enumerate(rows, 1):
            summary = counts.setdefault(code, [name, 0, 0, 0])
            summary[1] += 1
            summary[2] += value == 0
            summary[3] += value == -2
            display = "داده در دسترس نیست" if value == -2 else (f"{value / 10:g}" if unit == "celsius" else str(value))
            cells = [number, code, name, description, display, unit, value, captured, recorded, identifier]
            detail.append('<tr data-code="' + escape(code, quote=True) + '">' + ''.join(
                '<td>' + escape(str(cell)) + '</td>' for cell in cells
            ) + '</tr>')
        summary_rows = ''.join('<tr>' + ''.join('<td>' + escape(str(cell)) + '</td>' for cell in
            [code, name, count, zeros, failures]) + '</tr>'
            for code, (name, count, zeros, failures) in sorted(counts.items()))
        report = '''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>گزارش ثبت محلی دوربین‌ها</title>
<style>body{font-family:Tahoma,Arial,sans-serif;background:#f4f6fa;color:#182238;margin:24px}
table{border-collapse:collapse;width:100%;background:white;margin:16px 0}th,td{border:1px solid #dce2eb;padding:9px;text-align:right;white-space:nowrap}
th{background:#19385a;color:white;position:sticky;top:0}tr:nth-child(even){background:#edf3fa}input{padding:10px;width:280px;max-width:90%}.scroll{overflow:auto;max-height:70vh}td{unicode-bidi:plaintext}</style>
<h1>گزارش ثبت محلی دوربین‌ها</h1><p>ارسال این رکوردها به ERP انجام نشده است.</p>'''
        report += '<p>روز دریافت تصویر (میلادی، تهران): ' + escape(day) + ' | تعداد کل رکوردها: ' + str(len(rows)) + '</p>'
        report += '<p>آخرین به‌روزرسانی فایل: ' + escape(datetime.now(TEHRAN).isoformat(timespec="seconds")) + '</p>'
        report += '<h2>تعداد رکورد هر دوربین در این روز</h2><table><thead><tr><th>کد دوربین</th><th>نام</th><th>کل رکورد</th><th>مقدار ارسالی صفر</th><th>عدم دسترسی (-2)</th></tr></thead><tbody>' + summary_rows + '</tbody></table>'
        report += '<h2>جزئیات رکوردها</h2><p>زمان‌ها با منطقه زمانی تهران و ثانیه نمایش داده می‌شوند. مقدار خام همان مقدار آماده ارسال به ERP است؛ دما در ستون مقدار خوانا بر ۱۰ تقسیم شده است.</p><input id="camera" placeholder="فیلتر کد دوربین" aria-label="فیلتر کد دوربین"><span id="visible"></span><div class="scroll"><table id="records"><thead><tr>'
        report += ''.join('<th>' + heading + '</th>' for heading in ['ردیف', 'کد دوربین', 'نام', 'شرح منبع', 'مقدار خوانا', 'واحد', 'مقدار خام ERP', 'زمان دریافت / مشاهده', 'زمان ثبت در فایل', 'شناسه رکورد'])
        report += '</tr></thead><tbody>' + ''.join(detail) + '</tbody></table></div>'
        report += '''<script>const input=document.getElementById('camera');input.addEventListener('input',()=>{let count=0;for(const row of document.querySelectorAll('#records tbody tr')){row.hidden=!row.dataset.code.toLowerCase().includes(input.value.trim().toLowerCase());if(!row.hidden)count++}document.getElementById('visible').textContent=' تعداد نمایش: '+count});</script></html>'''
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory, suffix=".tmp", delete=False) as output:
                temporary = Path(output.name)
                output.write(report)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.directory / f"readings-{day}.html")
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
