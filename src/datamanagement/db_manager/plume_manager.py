import logging
import sqlite3

logger = logging.getLogger(__name__)


class PlumeMixin:

    def get_plumes(self):
        """Returns all plume modeling results."""
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, model_dt, file_name
                FROM plume
                ORDER BY model_dt DESC, file_name
                """
            ).fetchall()

            return [dict(row) for row in rows]

    def add_plume(self, file_name, model_dt):
        """Adds a new plume modeling result."""
        if not file_name:
            return False, "File name is mandatory."

        if not model_dt:
            return False, "Model datetime is mandatory."

        with self.get_connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO plume (model_dt, file_name) VALUES (?, ?)",
                    (model_dt, file_name),
                )
                conn.commit()
                return True, ""

            except sqlite3.IntegrityError:
                return False, "Plume already exists."

            except (OSError, ValueError) as e:
                return False, str(e)

    def delete_plume(self, file_name, model_dt=None):
        """
        Deletes a plume modeling result.

        If model_dt is provided, deletion is restricted to that specific
        model datetime. If not provided, all plume records with the given
        file_name are deleted.
        """
        if not file_name:
            return False, "File name is mandatory."

        with self.get_connection() as conn:
            if model_dt:
                cursor = conn.execute(
                    "DELETE FROM plume WHERE file_name = ? AND model_dt = ?",
                    (file_name, model_dt),
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM plume WHERE file_name = ?",
                    (file_name,),
                )

            if cursor.rowcount == 0:
                return False, "Plume not found."

            conn.commit()

        return True, ""
