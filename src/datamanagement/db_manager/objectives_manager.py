import os
import logging

logger = logging.getLogger(__name__)

class ObjectivesMixin:
    def get_all_objectives(self):
        """Returns all objectives ordered by created_at, including their observations."""
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT id, zone, objective, strategy, conclusion, created_at, updated_at
                FROM objective
                ORDER BY created_at ASC
            """).fetchall()
            
            objectives = []
            for row in rows:
                obj = dict(row)
                # Fetch associated observations
                obs_rows = conn.execute("""
                    SELECT id, data_type, form, filter
                    FROM observation
                    WHERE objective_id = ?
                """, (obj['id'],)).fetchall()
                obj['observations'] = [dict(o) for o in obs_rows]
                objectives.append(obj)
            return objectives

    def add_objective(self, data):
        """Inserts a new objective and its observations."""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO objective 
                (zone, objective, strategy, conclusion, created_at, updated_at)
                VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
            """, (data.get('zone'), data.get('objective'), data.get('strategy'), data.get('conclusion')))
            obj_id = cursor.lastrowid
            
            for obs in data.get('observations', []):
                conn.execute("""
                    INSERT INTO observation (data_type, form, filter, objective_id)
                    VALUES (?, ?, ?, ?)
                """, (obs['data_type'], obs['form'], obs['filter'], obj_id))
            conn.commit()
            return obj_id

    def update_objective(self, obj_id, data):
        """Updates an existing objective and replaces its observations."""
        with self.get_connection() as conn:
            conn.execute("""
                UPDATE objective
                SET zone=?, objective=?, strategy=?, conclusion=?, updated_at=datetime('now')
                WHERE id=?
            """, (data['zone'], data['objective'], data['strategy'], 
                  data['conclusion'], obj_id))
            
            # Delete old observations and insert new ones
            conn.execute(
                "DELETE FROM observation WHERE objective_id = ?", 
                (obj_id,)
            )
            
            for obs in data.get('observations', []):
                conn.execute("""
                    INSERT INTO observation (data_type, form, filter, objective_id)
                    VALUES (?, ?, ?, ?)
                """, (obs['data_type'], obs['form'], obs['filter'], obj_id))
            conn.commit()

    def delete_objective(self, obj_id):
        """Deletes an objective and all its associated observations."""
        with self.get_connection() as conn:
            conn.execute(
                "DELETE FROM observation WHERE objective_id = ?", 
                (obj_id,)
            )
            conn.execute(
                "DELETE FROM objective WHERE id = ?", 
                (obj_id,)
            )
            conn.commit()
