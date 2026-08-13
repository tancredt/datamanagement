import logging

logger = logging.getLogger(__name__)


class ObjectivesMixin:

    def get_all_objectives(self):
        """Returns all objectives ordered by created_at, including their observations."""
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, zone, objective, strategy, conclusion, created_at, updated_at
                FROM objective
                ORDER BY created_at ASC
                """
            ).fetchall()

            objectives = []

            for row in rows:
                obj = dict(row)

                obs_rows = conn.execute(
                    """
                    SELECT id, data_type, form, filter
                    FROM observation
                    WHERE objective_id = ?
                    """,
                    (obj["id"],),
                ).fetchall()

                obj["observations"] = [dict(o) for o in obs_rows]
                objectives.append(obj)

            return objectives

    def add_objective(self, data):
        """Inserts a new objective and its observations."""
        data = data or {}

        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO objective
                (zone, objective, strategy, conclusion, created_at, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
                """,
                (
                    data.get("zone"),
                    data.get("objective"),
                    data.get("strategy"),
                    data.get("conclusion"),
                ),
            )

            obj_id = cursor.lastrowid

            observations = data.get("observations", []) or []

            for obs in observations:
                conn.execute(
                    """
                    INSERT INTO observation (data_type, form, filter, objective_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        obs.get("data_type"),
                        obs.get("form"),
                        obs.get("filter"),
                        obj_id,
                    ),
                )

            conn.commit()

            return obj_id

    def update_objective(self, obj_id, data):
        """Updates an existing objective and replaces its observations."""
        data = data or {}

        if obj_id is None:
            return False, "Objective ID is required."

        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE objective
                SET zone=?, objective=?, strategy=?, conclusion=?, updated_at=datetime('now')
                WHERE id=?
                """,
                (
                    data.get("zone"),
                    data.get("objective"),
                    data.get("strategy"),
                    data.get("conclusion"),
                    obj_id,
                ),
            )

            if cursor.rowcount == 0:
                return False, "Objective not found."

            conn.execute(
                "DELETE FROM observation WHERE objective_id = ?",
                (obj_id,),
            )

            observations = data.get("observations", []) or []

            for obs in observations:
                conn.execute(
                    """
                    INSERT INTO observation (data_type, form, filter, objective_id)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        obs.get("data_type"),
                        obs.get("form"),
                        obs.get("filter"),
                        obj_id,
                    ),
                )

            conn.commit()

        return True, ""

    def delete_objective(self, obj_id):
        """Deletes an objective and all its associated observations."""
        if obj_id is None:
            return False, "Objective ID is required."

        with self.get_connection() as conn:
            conn.execute(
                "DELETE FROM observation WHERE objective_id = ?",
                (obj_id,),
            )

            cursor = conn.execute(
                "DELETE FROM objective WHERE id = ?",
                (obj_id,),
            )

            if cursor.rowcount == 0:
                return False, "Objective not found."

            conn.commit()

        return True, ""
