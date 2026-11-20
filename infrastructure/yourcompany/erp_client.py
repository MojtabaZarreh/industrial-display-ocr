from __future__ import annotations
import logging
from collections.abc import Mapping
from typing import Any
import pymssql

logger = logging.getLogger(__name__)

class YourCompanyERPClient:
    def __init__(
        self,
        *,
        host: str,
        user: str,
        password: str,
        database: str,
        login_timeout: int = 5,
        timeout: int = 15,
    ) -> None:
        self._host = host
        self._user = user
        self._password = password
        self._database = database
        self._login_timeout = login_timeout
        self._timeout = timeout

    def insert_temperature(
        self,
        data: Mapping[str, Any],
    ) -> None:
        required_fields = {
            "Date",
            "Time",
            "Temperature",
            "CreateDateTime",
            "RecordType",
        }

        missing_fields = required_fields - data.keys()

        if missing_fields:
            raise ValueError(
                f"Missing ERP fields: {', '.join(sorted(missing_fields))}"
            )

        connection = None

        try:
            connection = pymssql.connect(
                server=self._host,
                user=self._user,
                password=self._password,
                database=self._database,
                login_timeout=self._login_timeout,
                timeout=self._timeout,
                charset="UTF-8",
            )

            with connection.cursor() as cursor:
                query = """
                    INSERT INTO ServerRoomTemp
                    (
                        [Date],
                        [Time],
                        [Temperature],
                        [CreateDateTime],
                        [RecordType]
                    )
                    VALUES (%s, %s, %s, %s, %s)
                """

                cursor.execute(
                    query,
                    (
                        data["Date"],
                        data["Time"],
                        data["Temperature"],
                        data["CreateDateTime"],
                        data["RecordType"],
                    ),
                )

            connection.commit()

            logger.debug(
                "Temperature successfully inserted into ERP."
            )

        except Exception:
            if connection is not None:
                connection.rollback()

            logger.exception(
                "Failed to insert temperature into ERP."
            )
            raise

        finally:
            if connection is not None:
                connection.close()


    def get_daily_temperatures(
        self,
        *,
        report_date: str,
        record_types: list[str],
    ) -> dict[str, list[float]]:

        if not report_date:
            raise ValueError("Report date cannot be empty.")

        if not record_types:
            raise ValueError("Record types cannot be empty.")

        results: dict[str, list[float]] = {
            record_type: []
            for record_type in record_types
        }

        connection = None

        try:
            connection = pymssql.connect(
                server=self._host,
                user=self._user,
                password=self._password,
                database=self._database,
                login_timeout=self._login_timeout,
                timeout=self._timeout,
                charset="UTF-8",
            )

            with connection.cursor() as cursor:
                query = """
                    SELECT
                        [RecordType],
                        [Temperature]
                    FROM ServerRoomTemp
                    WHERE [Date] = %s
                    AND [RecordType] IN (%s)
                """

                placeholders = ", ".join(
                    ["%s"] * len(record_types)
                )

                query = query.replace(
                    "IN (%s)",
                    f"IN ({placeholders})",
                )

                cursor.execute(
                    query,
                    (report_date, *record_types),
                )

                rows = cursor.fetchall()

                for record_type, temperature in rows:
                    if temperature is None:
                        continue

                    results[record_type].append(
                        float(temperature)
                    )

            logger.info(
                "Retrieved daily temperatures from ERP. "
                "Date: %s, Records: %s",
                report_date,
                sum(len(values) for values in results.values()),
            )

            return results

        except Exception:
            logger.exception(
                "Failed to retrieve daily temperatures from ERP."
            )
            raise

        finally:
            if connection is not None:
                connection.close()
