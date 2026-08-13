"""Map and marker management."""

import os
import shutil
import logging

logger = logging.getLogger(__name__)


class MapMarkerMixin:
    """Mixin providing map and marker CRUD operations."""

    def add_map(self, image_path):
        """Adds a map image file name to the database and copies it to mapping directory."""
        fname = os.path.basename(image_path)
        dest_path = os.path.join(self.mapping_dir, fname)

        shutil.copy2(image_path, dest_path)

        with self.get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sitemap (file_name) VALUES (?)",
                (fname,),
            )
            conn.commit()

        return fname

    def delete_map(self, map_filename):
        """Deletes a map file name from the database and removes the physical file."""
        file_path = os.path.join(self.mapping_dir, map_filename)

        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError as e:
                logger.error(
                    "Failed to delete physical map file %s: %s",
                    file_path,
                    e,
                )

        with self.get_connection() as conn:
            conn.execute(
                "DELETE FROM sitemap WHERE file_name = ?",
                (map_filename,),
            )
            conn.commit()

    def get_maps(self):
        """Returns list of all map filenames."""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT file_name FROM sitemap ORDER BY file_name"
            ).fetchall()

            return [row["file_name"] for row in rows]

    def get_marker_labels_for_map(self, map_filename):
        """Returns set of marker labels placed on a specific map."""
        with self.get_connection() as conn:
            query = """
                SELECT m.label
                FROM marker m
                JOIN sitemap_marker sm ON m.id = sm.marker_id
                JOIN sitemap s ON sm.sitemap_id = s.id
                WHERE s.file_name = ?
            """
            rows = conn.execute(query, (map_filename,)).fetchall()

            return {row["label"] for row in rows}

    def get_next_marker_label(self):
        """Generates the next available alphabetical label (A, B, ..., Z, AA, AB, ...)."""
        used_labels = set(self.get_markers())

        max_idx = -1

        for label in used_labels:
            label_upper = str(label).strip().upper()

            if not label_upper.isalpha():
                continue

            idx = 0

            for char in label_upper:
                idx = idx * 26 + (ord(char) - 64)

            idx -= 1
            max_idx = max(max_idx, idx)

        next_idx = max_idx + 1
        idx = next_idx + 1
        result = []

        while idx > 0:
            idx, rem = divmod(idx - 1, 26)
            result.append(chr(65 + rem))

        return "".join(reversed(result))

    def add_marker(self, label, description="", latitude=None, longitude=None):
        """Adds a new marker to the database, or updates it if it already exists."""
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO marker (label, description, latitude, longitude)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(label) DO UPDATE SET
                    description = excluded.description,
                    latitude = excluded.latitude,
                    longitude = excluded.longitude
                """,
                (label, description, latitude, longitude),
            )
            conn.commit()

            return self.get_marker_id_by_label(label, conn=conn)

    def update_marker(
        self,
        label,
        description=None,
        latitude=None,
        longitude=None,
        clear_latitude=False,
        clear_longitude=False
    ):
        """
        Updates an existing marker's information.

        To explicitly clear latitude or longitude to NULL, use
        clear_latitude=True or clear_longitude=True.
        """
        with self.get_connection() as conn:
            updates = []
            params = []

            if description is not None:
                updates.append("description = ?")
                params.append(description)

            if clear_latitude:
                updates.append("latitude = NULL")
            elif latitude is not None:
                updates.append("latitude = ?")
                params.append(latitude)

            if clear_longitude:
                updates.append("longitude = NULL")
            elif longitude is not None:
                updates.append("longitude = ?")
                params.append(longitude)

            if updates:
                params.append(label)
                query = f"UPDATE marker SET {', '.join(updates)} WHERE label = ?"
                cursor = conn.execute(query, params)

                if cursor.rowcount == 0:
                    return False, "Marker not found."

                conn.commit()

        return True, ""

    def delete_marker(self, label):
        """Deletes a marker from the database."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM marker WHERE label = ?",
                (label,),
            )

            if cursor.rowcount == 0:
                return False, "Marker not found."

            conn.commit()

        return True, ""

    def place_marker_on_map(self, marker_label, map_filename, x_coord, y_coord):
        """
        Places a marker on a specific map with pixel coordinates.

        If the marker already exists on this map, updates the existing entry
        with the new position.
        """
        with self.get_connection() as conn:
            marker_id = self.get_marker_id_by_label(marker_label, conn=conn)

            map_row = conn.execute(
                "SELECT id FROM sitemap WHERE file_name = ?",
                (map_filename,),
            ).fetchone()

            if not marker_id:
                return False, f"Marker '{marker_label}' not found."

            if not map_row:
                return False, f"Map '{map_filename}' not found."

            conn.execute(
                """
                INSERT INTO sitemap_marker (marker_id, sitemap_id, x_coord, y_coord)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(marker_id, sitemap_id) DO UPDATE SET
                    x_coord = excluded.x_coord,
                    y_coord = excluded.y_coord
                """,
                (marker_id, map_row["id"], x_coord, y_coord),
            )

            conn.commit()

        return True, ""

    def remove_marker_from_map(self, marker_label, map_filename):
        """Removes a marker from a specific map."""
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                DELETE FROM sitemap_marker
                WHERE marker_id = (SELECT id FROM marker WHERE label = ?)
                  AND sitemap_id = (SELECT id FROM sitemap WHERE file_name = ?)
                """,
                (marker_label, map_filename),
            )

            if cursor.rowcount == 0:
                return False, "Marker was not found on that map."

            conn.commit()

        return True, ""

    def get_markers_for_map(self, map_filename):
        """Returns all markers placed on a specific map with their coordinates."""
        with self.get_connection() as conn:
            query = """
                SELECT m.label,
                       m.description,
                       m.latitude,
                       m.longitude,
                       sm.x_coord,
                       sm.y_coord
                FROM marker m
                JOIN sitemap_marker sm ON m.id = sm.marker_id
                JOIN sitemap s ON sm.sitemap_id = s.id
                WHERE s.file_name = ?
            """
            rows = conn.execute(query, (map_filename,)).fetchall()

            return [dict(row) for row in rows]

    def get_maps_data(self):
        """Returns dictionary of all maps with their associated markers."""
        maps_data = {}

        for fname in self.get_maps():
            maps_data[fname] = self.get_markers_for_map(fname)

        return maps_data
