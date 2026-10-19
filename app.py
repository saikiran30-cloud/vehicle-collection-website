
import os
import re
import csv
import io
import sqlite3
import secrets
from pathlib import Path
from datetime import datetime
from functools import wraps

from flask import (
    Flask, request, jsonify, render_template, redirect,
    url_for, session, flash, send_from_directory, make_response
)
from werkzeug.utils import secure_filename
from PIL import (
    Image, ImageOps, ImageEnhance, ImageFilter,
    UnidentifiedImageError
)
import pytesseract

# Optional image format support
try:
    import pillow_avif
except ImportError:
    pillow_avif = None

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None


# ==================================================
# 1. APPLICATION SETTINGS
# ==================================================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "collection.db"

DATA_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY", "change-this-secret-key-before-online-use"
)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

# Tesseract path on your Windows laptop
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

if os.path.exists(TESSERACT_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

USERNAME = "mahesh"
PASSWORD = "mahesh@321"

ALLOWED_EXTENSIONS = {
    "jpg", "jpeg", "png", "webp", "bmp",
    "tif", "tiff", "gif", "heic", "heif",
    "avif", "jfif", "jp2", "ppm", "pgm", "pbm"
}


# ==================================================
# 2. DATABASE
# ==================================================

def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS washing_centres (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS supply_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                centre_id INTEGER NOT NULL,
                supply_date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (centre_id)
                    REFERENCES washing_centres(id)
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS supply_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id INTEGER NOT NULL,
                material_name TEXT NOT NULL,
                quantity REAL NOT NULL,
                unit TEXT NOT NULL,
                amount REAL NOT NULL,
                FOREIGN KEY (entry_id)
                    REFERENCES supply_entries(id)
                    ON DELETE CASCADE
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_number TEXT NOT NULL DEFAULT '',
                amount REAL NOT NULL DEFAULT 0,
                payment_method TEXT NOT NULL DEFAULT 'Cash',
                photo_filename TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT ''
            )
        """)

        columns = {
            row["name"]
            for row in db.execute("PRAGMA table_info(vehicles)")
        }

        required_columns = {
    "vehicle_number": "TEXT NOT NULL DEFAULT ''",
    "amount": "REAL NOT NULL DEFAULT 0",
    "payment_method": "TEXT NOT NULL DEFAULT 'Cash'",
    "photo_filename": "TEXT NOT NULL DEFAULT ''",
    "created_at": "TEXT NOT NULL DEFAULT ''",
    "updated_at": "TEXT NOT NULL DEFAULT ''",
}

        for name, definition in required_columns.items():
            if name not in columns:
                db.execute(
                    f"ALTER TABLE vehicles ADD COLUMN {name} {definition}"
                )


init_db()


# ==================================================
# 3. LOGIN AND SECURITY
# ==================================================

def login_required(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({
                    "success": False,
                    "error": "Please sign in again."
                }), 401

            return redirect(url_for("login"))

        return function(*args, **kwargs)

    return wrapper


def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)

    return session["csrf_token"]


@app.context_processor
def inject_template_values():
    return {"csrf_token": get_csrf_token}


@app.before_request
def check_csrf():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None

    if request.endpoint == "login":
        return None

    supplied = (
        request.headers.get("X-CSRF-Token")
        or request.form.get("csrf_token")
    )

    expected = session.get("csrf_token")

    if (
        expected
        and supplied
        and secrets.compare_digest(str(expected), str(supplied))
    ):
        return None

    if request.path.startswith("/api/"):
        return jsonify({
            "success": False,
            "error": "Security token expired. Refresh the page and try again."
        }), 400

    flash("Security token expired. Please try again.", "error")
    return redirect(url_for("login"))



# ==================================================
# 4. IMAGE HANDLING — IMPROVED
# ==================================================

def allowed_file(filename):
    return bool(filename and filename.strip())

def get_uploaded_file():
    uploaded = (
        request.files.get("photo")
        or request.files.get("image")
        or request.files.get("file")
    )

    if not uploaded or not uploaded.filename:
        raise ValueError("Please choose or capture an image first.")

    if not allowed_file(uploaded.filename):
        raise ValueError("Please select a valid image file.")

    return uploaded


def decode_image(uploaded):
    """Decode supported image formats and correct EXIF orientation."""
    try:
        uploaded.stream.seek(0)

        with Image.open(uploaded.stream) as original:
            if getattr(original, "n_frames", 1) > 1:
                original.seek(0)

            width, height = original.size

            if width <= 0 or height <= 0:
                raise ValueError("The image dimensions are invalid.")

            if width * height > 40_000_000:
                raise ValueError(
                    "Image is too large. Please choose an image under 40 megapixels."
                )

            image = ImageOps.exif_transpose(original)
            image.load()
            image = image.convert("RGB")

            return image.copy()

    except ValueError:
        raise
    except Exception as error:
        raise ValueError(
            "Cannot decode this image. Try JPG or PNG, or install the "
            "decoder required for its format."
        ) from error


def save_image_as_jpg(image, original_name):
    safe_name = Path(
        secure_filename(original_name or "vehicle")
    ).stem or "vehicle"

    filename = (
        datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        + "_"
        + safe_name
        + ".jpg"
    )

    image.save(
        UPLOAD_DIR / filename,
        format="JPEG",
        quality=95,
        optimize=True
    )

    return filename


# ==================================================
# 5. ADVANCED NUMBER PLATE OCR
# ==================================================

def clean_number(text):
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def find_indian_plates(text):
    """
    Find likely Indian registration numbers.
    These patterns are candidates, not proof that a number is valid.
    """
    compact = clean_number(text)

    patterns = [
        # Standard registrations, e.g. TS09AB1234
        r"[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{1,4}",

        # Bharat series, e.g. 22BH1234AA
        r"[0-9]{2}BH[0-9]{4}[A-Z]{1,2}",
    ]

    found = []

    for pattern in patterns:
        found.extend(re.findall(pattern, compact))

    # Keep first occurrence of each result, longest first.
    return sorted(set(found), key=len, reverse=True)


def prepare_ocr_images(image):
    """
    Generate different versions of the image for OCR.
    """
    versions = []

    gray = ImageOps.grayscale(image)

    # Enlarge small images without unnecessarily enlarging huge ones.
    if gray.width < 1800:
        scale = min(3.0, 1800 / max(gray.width, 1))
        gray = gray.resize(
            (
                max(1, int(gray.width * scale)),
                max(1, int(gray.height * scale))
            ),
            Image.Resampling.LANCZOS
        )

    # Normal grayscale and enhanced grayscale.
    versions.append(gray)
    versions.append(ImageOps.autocontrast(gray))

    contrast = ImageEnhance.Contrast(gray).enhance(2.0)
    versions.append(contrast)

    # Sharpen the enhanced image.
    versions.append(
        contrast.filter(
            ImageFilter.UnsharpMask(
                radius=2,
                percent=180,
                threshold=3
            )
        )
    )

    # A mild denoise can help with compression artifacts.
    versions.append(
        gray.filter(ImageFilter.MedianFilter(size=3))
    )

    # Thresholding methods, when OpenCV is available.
    if cv2 is not None and np is not None:
        try:
            array = np.array(gray)
            array = cv2.medianBlur(array, 3)

            _, otsu = cv2.threshold(
                array,
                0,
                255,
                cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )

            adaptive = cv2.adaptiveThreshold(
                array,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                9
            )

            # Some plates have light text on a dark background.
            versions.append(Image.fromarray(otsu))
            versions.append(Image.fromarray(255 - otsu))
            versions.append(Image.fromarray(adaptive))
            versions.append(Image.fromarray(255 - adaptive))

        except Exception:
            pass

    return versions


def find_plate_regions(image):
    """
    Find possible plate-shaped regions with OpenCV.
    This is a heuristic: signs and other rectangular objects may also
    be selected, so OCR must still verify the text.
    """
    if cv2 is None or np is None:
        return []

    try:
        rgb = np.array(image)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

        height, width = gray.shape[:2]
        if width < 30 or height < 30:
            return []

        # Keep processing reasonable for large photos.
        scale = min(1.0, 1600 / max(width, height))

        if scale < 1.0:
            small = cv2.resize(
                gray,
                (int(width * scale), int(height * scale))
            )
        else:
            small = gray

        sh, sw = small.shape[:2]
        blurred = cv2.bilateralFilter(small, 9, 75, 75)

        edges = cv2.Canny(blurred, 50, 160)

        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (13, 5)
        )

        joined = cv2.morphologyEx(
            edges, cv2.MORPH_CLOSE, kernel
        )

        contours, _ = cv2.findContours(
            joined,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE
        )

        candidates = []

        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)

            area = w * h
            ratio = w / max(h, 1)

            # Broad range to allow perspective and differently sized plates.
            if area < 500 or area > sw * sh * 0.35:
                continue

            if not 1.5 <= ratio <= 7.5:
                continue

            # Add padding around the candidate region.
            pad_x = max(8, int(w * 0.08))
            pad_y = max(8, int(h * 0.25))

            x1 = max(0, x - pad_x)
            y1 = max(0, y - pad_y)
            x2 = min(sw, x + w + pad_x)
            y2 = min(sh, y + h + pad_y)

            crop = small[y1:y2, x1:x2]

            if crop.size == 0:
                continue

            # Restore the crop to the original image's coordinate scale.
            if scale < 1.0:
                crop = cv2.resize(
                    crop,
                    (
                        max(1, int(crop.shape[1] / scale)),
                        max(1, int(crop.shape[0] / scale))
                    ),
                    interpolation=cv2.INTER_CUBIC
                )

            candidates.append((area, Image.fromarray(crop)))

        # Try larger candidates first and cap processing time.
        candidates.sort(key=lambda item: item[0], reverse=True)

        return [crop for _, crop in candidates[:12]]

    except Exception:
        app.logger.exception("Plate-region detection failed")
        return []


def read_plate(image):
    """
    Run OCR over the full image and likely plate regions.
    Return a matching registration candidate when possible.
    Otherwise return a cautious OCR result for manual correction.
    """
    configs = [
        "--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        "--oem 3 --psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        "--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        "--oem 3 --psm 11 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    ]

    # Check likely plate crops first, then the entire image.
    crops = find_plate_regions(image)
    sources = crops + [image]

    all_text = []

    for source in sources:
        for version in prepare_ocr_images(source):
            for config in configs:
                try:
                    result = pytesseract.image_to_string(
                        version,
                        config=config,
                        timeout=5
                    )

                    if not result:
                        continue

                    all_text.append(result)

                    matches = find_indian_plates(result)

                    if matches:
                        return matches[0]

                except pytesseract.TesseractNotFoundError:
                    raise ValueError(
                        "Tesseract OCR was not found. Check the Tesseract "
                        "installation path in app.py."
                    )
                except RuntimeError:
                    # A timeout or OCR-specific failure should not stop
                    # other image variants from being tried.
                    continue
                except Exception:
                    continue

    # Combine OCR outputs in case the registration was split across lines.
    matches = find_indian_plates(" ".join(all_text))

    if matches:
        return matches[0]

    # Only return a fallback if it looks like a reasonably sized token.
    # This may still be ordinary text; the dashboard user must verify it.
    cleaned = [
        clean_number(result)
        for result in all_text
    ]

    cleaned = [
        value for value in cleaned
        if 5 <= len(value) <= 12
    ]

    if cleaned:
        return max(cleaned, key=len)

    return ""


# ==================================================
# 5. NUMBER PLATE OCR
# ==================================================

def clean_number(text):
    return re.sub(r"[^A-Z0-9]", "", str(text or "").upper())


def find_indian_plates(text):
    """
    Find common Indian vehicle registration number patterns.

    Examples:
    TS09AB1234
    TS09A1234
    AP39CD5678
    22BH1234AA
    """

    compact = clean_number(text)

    patterns = [
        r"[A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{1,4}",
        r"[0-9]{2}BH[0-9]{4}[A-Z]{1,2}",
    ]

    matches = []

    for pattern in patterns:
        matches.extend(re.findall(pattern, compact))

    # Prefer longer matches, while removing duplicate values.
    matches = list(set(matches))
    matches.sort(key=len, reverse=True)

    return matches


def prepare_ocr_images(image):
    """
    Create multiple versions of the image to improve OCR.
    """

    versions = [image.copy()]

    gray = ImageOps.grayscale(image)

    # Enlarge small images to make letters easier to read.
    if gray.width < 1400:
        scale = min(3, 1400 / max(gray.width, 1))

        gray = gray.resize(
            (
                max(1, int(gray.width * scale)),
                max(1, int(gray.height * scale))
            ),
            Image.Resampling.LANCZOS
        )

    versions.append(gray)

    contrast = ImageEnhance.Contrast(gray).enhance(2.0)
    versions.append(contrast)

    sharp = ImageEnhance.Sharpness(contrast).enhance(2.0)
    versions.append(sharp)

    versions.append(
        gray.filter(
            ImageFilter.UnsharpMask(
                radius=2,
                percent=180,
                threshold=3
            )
        )
    )

    # Additional thresholding if OpenCV is installed.
    if cv2 is not None and np is not None:
        try:
            array = np.array(gray)

            array = cv2.medianBlur(array, 3)

            _, otsu = cv2.threshold(
                array,
                0,
                255,
                cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )

            adaptive = cv2.adaptiveThreshold(
                array,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                9
            )

            versions.append(Image.fromarray(otsu))
            versions.append(Image.fromarray(adaptive))

        except Exception:
            pass

    return versions


def read_plate(image):
    """
    Read the plate using several OCR configurations.
    Return a complete-looking number when one is detected.
    """

    all_text = []

    configs = [
        "--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        "--oem 3 --psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        "--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
        "--oem 3 --psm 11 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    ]

    for version in prepare_ocr_images(image):
        for config in configs:
            try:
                result = pytesseract.image_to_string(
                    version,
                    config=config,
                    timeout=8
                )

                if not result:
                    continue

                all_text.append(result)

                matches = find_indian_plates(result)

                if matches:
                    return matches[0]

            except Exception:
                # Continue trying other image versions/configurations.
                continue

    combined_text = " ".join(all_text)
    matches = find_indian_plates(combined_text)

    if matches:
        return matches[0]

    # If the plate pattern is not detected, return the longest
    # reasonable OCR result so the user can manually correct it.
    cleaned = [
        clean_number(result)
        for result in all_text
    ]

    cleaned = [
        value for value in cleaned
        if 4 <= len(value) <= 15
    ]

    if cleaned:
        return max(cleaned, key=len)

    return ""


# ==================================================
# 6. RECORD HELPERS AND TOTALS
# ==================================================

def record_to_dict(row):
    record = dict(row)
    record["amount"] = float(record.get("amount") or 0)

    filename = record.get("photo_filename", "")

    record["photo_url"] = (
        url_for("uploaded_file", filename=filename)
        if filename else ""
    )

    return record


def calculate_stats(db):
    rows = db.execute("""
        SELECT
            payment_method,
            COUNT(*) AS count,
            COALESCE(SUM(amount), 0) AS total
        FROM vehicles
        GROUP BY payment_method
    """).fetchall()

    overall = db.execute("""
        SELECT
            COUNT(*) AS count,
            COALESCE(SUM(amount), 0) AS total
        FROM vehicles
    """).fetchone()

    stats = {
        "vehicle_count": int(overall["count"]),
        "total_amount": float(overall["total"]),
        "gpay_total": 0,
        "gpay_count": 0,
        "phonepe_total": 0,
        "phonepe_count": 0,
        "cash_total": 0,
        "cash_count": 0,
    }

    for row in rows:
        method = (row["payment_method"] or "").lower().replace(" ", "")

        if method in {"googlepay", "gpay"}:
            prefix = "gpay"
        elif method == "phonepe":
            prefix = "phonepe"
        else:
            prefix = "cash"

        stats[prefix + "_total"] += float(row["total"] or 0)
        stats[prefix + "_count"] += int(row["count"] or 0)

    return stats


# ==================================================
# 7. LOGIN PAGES
# ==================================================

@app.route("/")
def home():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))

    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if (
            secrets.compare_digest(username, USERNAME)
            and secrets.compare_digest(password, PASSWORD)
        ):
            session.clear()
            session["logged_in"] = True
            get_csrf_token()

            return redirect(url_for("dashboard"))

        flash("Incorrect username or password.", "error")

    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html")


@app.route("/supplies")
@login_required
def supplies_page():
    return render_template("supplies.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


# ==================================================
# 8. GET VEHICLE RECORDS
# ==================================================

@app.route("/api/vehicles", methods=["GET"])
@login_required
def list_vehicles():
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM vehicles ORDER BY id DESC"
        ).fetchall()

        records = [record_to_dict(row) for row in rows]
        stats = calculate_stats(db)

    return jsonify({
        "success": True,
        "records": records,
        "vehicles": records,
        "stats": stats,
        **stats
    })


# ==================================================
# 9. SCAN IMAGE
# ==================================================

@app.route("/api/scan", methods=["POST"])
@login_required
def scan_image():
    try:
        uploaded = get_uploaded_file()
        image = decode_image(uploaded)
        number = read_plate(image)

        return jsonify({
            "success": True,
            "vehicle_number": number,
            "number": number,
            "message": (
                "Number detected. Check it before saving."
                if number
                else "No readable number detected. Use a clearer, closer image "
                     "or type the number manually."
            )
        })

    except ValueError as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception:
        app.logger.exception("Image scan failed")

        return jsonify({
            "success": False,
            "error": "Image scan failed. Please try another image."
        }), 500


# ==================================================
# 10. SAVE VEHICLE
# ==================================================

@app.route("/api/vehicles", methods=["POST"])
@login_required
def create_vehicle():
    filename = None

    try:
        uploaded = get_uploaded_file()
        image = decode_image(uploaded)

        filename = save_image_as_jpg(image, uploaded.filename)

        vehicle_number = clean_number(
            request.form.get("vehicle_number", "")
        )

        # Scan automatically if the user has not entered a number.
        if not vehicle_number:
            vehicle_number = read_plate(image)

        try:
            amount = float(request.form.get("amount", "0"))

            if amount < 0:
                raise ValueError

        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "error": "Enter a valid amount."
            }), 400

        payment_method = request.form.get(
            "payment_method", "Cash"
        ).strip()

        if payment_method not in {"Google Pay", "PhonePe", "Cash"}:
            payment_method = "Cash"

        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        
        with get_db() as db:
            cursor = db.execute("""
                INSERT INTO vehicles (
                    vehicle_number,
                    amount,
                    payment_method,
                    photo_filename,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                vehicle_number,
                amount,
                payment_method,
                filename,
                created_at,
                created_at
            ))

            row = db.execute(
                "SELECT * FROM vehicles WHERE id = ?",
                (cursor.lastrowid,)
            ).fetchone()

   

            row = db.execute(
                "SELECT * FROM vehicles WHERE id = ?",
                (cursor.lastrowid,)
            ).fetchone()

        return jsonify({
            "success": True,
            "message": "Vehicle saved successfully.",
            "record": record_to_dict(row),
            "vehicle_number": vehicle_number,
            "ocr_found": bool(vehicle_number)
        }), 201

    
    except ValueError as error:
        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception as error:
        app.logger.exception("Saving vehicle failed")
        return jsonify({
            "success": False,
            "error": str(error)
        }), 500



# ==================================================
# 11. EDIT VEHICLE
# ==================================================

@app.route("/api/vehicles/<int:vehicle_id>", methods=["PUT", "PATCH"])
@login_required
def update_vehicle(vehicle_id):
    data = request.get_json(silent=True) or request.form

    vehicle_number = clean_number(
        data.get("vehicle_number", "")
    )

    try:
        amount = float(data.get("amount", 0))

        if amount < 0:
            raise ValueError

    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "Enter a valid amount."
        }), 400

    payment_method = str(
        data.get("payment_method", "Cash")
    ).strip()

    if payment_method not in {"Google Pay", "PhonePe", "Cash"}:
        payment_method = "Cash"

    with get_db() as db:
        existing = db.execute(
            "SELECT * FROM vehicles WHERE id = ?",
            (vehicle_id,)
        ).fetchone()

        if not existing:
            return jsonify({
                "success": False,
                "error": "Vehicle record not found."
            }), 404

        db.execute("""
            UPDATE vehicles
            SET vehicle_number = ?,
                amount = ?,
                payment_method = ?
            WHERE id = ?
        """, (
            vehicle_number,
            amount,
            payment_method,
            vehicle_id
        ))

        updated = db.execute(
            "SELECT * FROM vehicles WHERE id = ?",
            (vehicle_id,)
        ).fetchone()

    return jsonify({
        "success": True,
        "message": "Vehicle updated.",
        "record": record_to_dict(updated)
    })


# ==================================================
# 12. DELETE VEHICLE
# ==================================================

@app.route("/api/vehicles/<int:vehicle_id>", methods=["DELETE"])
@login_required
def delete_vehicle(vehicle_id):
    with get_db() as db:
        row = db.execute(
            "SELECT photo_filename FROM vehicles WHERE id = ?",
            (vehicle_id,)
        ).fetchone()

        if not row:
            return jsonify({
                "success": False,
                "error": "Vehicle record not found."
            }), 404

        db.execute(
            "DELETE FROM vehicles WHERE id = ?",
            (vehicle_id,)
        )

    filename = row["photo_filename"]

    if filename:
        try:
            (UPLOAD_DIR / filename).unlink(missing_ok=True)
        except OSError:
            pass

    return jsonify({
        "success": True,
        "message": "Vehicle deleted."
    })


# ==================================================
# 13. PAYMENT TOTALS
# ==================================================

@app.route("/api/totals", methods=["GET"])
@login_required
def totals():
    with get_db() as db:
        stats = calculate_stats(db)

    return jsonify({
        "success": True,
        **stats,
        "stats": stats
    })


# ==================================================
# 14. SERVE SAVED PHOTOS
# ==================================================

@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# Compatibility with older JavaScript versions
@app.route("/photos/<path:filename>")
@login_required
def old_photo_route(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ==================================================
# 15. EXPORT CSV
# ==================================================

@app.route("/api/export.csv", methods=["GET"])
@login_required
def export_csv():
    with get_db() as db:
        rows = db.execute("""
            SELECT id, vehicle_number, amount,
                   payment_method, photo_filename, created_at
            FROM vehicles
            ORDER BY id DESC
        """).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "ID",
        "Vehicle Number",
        "Amount",
        "Payment Method",
        "Photo Filename",
        "Created At"
    ])

    for row in rows:
        writer.writerow([
            row["id"],
            row["vehicle_number"],
            row["amount"],
            row["payment_method"],
            row["photo_filename"],
            row["created_at"]
        ])

    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = (
        "attachment; filename=vehicle_collection.csv"
    )

    return response

# ==================================================
# SHAMPOO SUPPLY HISTORY
# ==================================================

@app.route("/api/supplies", methods=["GET"])
@login_required
def list_supplies():
    customer = request.args.get("customer", "").strip()

    with get_db() as db:
        if customer:
            centres = db.execute("""
                SELECT id, name
                FROM washing_centres
                WHERE name LIKE ? ESCAPE '\\'
                ORDER BY name COLLATE NOCASE
            """, (
                "%" + customer.replace("\\", "\\\\")
                              .replace("%", "\\%")
                              .replace("_", "\\_") + "%",
            )).fetchall()
        else:
            centres = db.execute("""
                SELECT id, name
                FROM washing_centres
                ORDER BY name COLLATE NOCASE
            """).fetchall()

        history = []

        for centre in centres:
            entries = db.execute("""
                SELECT id, supply_date, created_at
                FROM supply_entries
                WHERE centre_id = ?
                ORDER BY supply_date DESC, id DESC
            """, (centre["id"],)).fetchall()

            entry_list = []

            for entry in entries:
                items = db.execute("""
                    SELECT id, material_name, quantity, unit, amount
                    FROM supply_items
                    WHERE entry_id = ?
                    ORDER BY id
                """, (entry["id"],)).fetchall()

                item_list = [dict(item) for item in items]
                entry_total = sum(float(item["amount"]) for item in item_list)

                entry_list.append({
                    "id": entry["id"],
                    "supply_date": entry["supply_date"],
                    "created_at": entry["created_at"],
                    "items": item_list,
                    "total_amount": entry_total
                })

            history.append({
                "id": centre["id"],
                "name": centre["name"],
                "entries": entry_list,
                "total_amount": sum(
                    entry["total_amount"] for entry in entry_list
                )
            })

    return jsonify({"success": True, "centres": history})


@app.route("/api/supplies", methods=["POST"])
@login_required
def create_supply():
    data = request.get_json(silent=True) or {}

    centre_name = str(data.get("customer_name", "")).strip()
    supply_date = str(data.get("supply_date", "")).strip()
    items = data.get("items")

    if not centre_name:
        return jsonify({
            "success": False,
            "error": "Enter the washing centre name."
        }), 400

    if len(centre_name) > 150:
        return jsonify({
            "success": False,
            "error": "Washing centre name is too long."
        }), 400

    try:
        parsed_date = datetime.strptime(supply_date, "%Y-%m-%d")
        if parsed_date.strftime("%Y-%m-%d") != supply_date:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({
            "success": False,
            "error": "Choose a valid supply date."
        }), 400

    if not isinstance(items, list) or not items:
        return jsonify({
            "success": False,
            "error": "Add at least one shampoo or material."
        }), 400

    if len(items) > 100:
        return jsonify({
            "success": False,
            "error": "You can add up to 100 materials in one entry."
        }), 400

    cleaned_items = []

    for item in items:
        if not isinstance(item, dict):
            return jsonify({
                "success": False,
                "error": "Invalid material details."
            }), 400

        material_name = str(item.get("material_name", "")).strip()
        unit = str(item.get("unit", "")).strip().lower()

        if not material_name or len(material_name) > 150:
            return jsonify({
                "success": False,
                "error": "Enter a valid name for every material."
            }), 400

        if unit not in {"litres", "pieces"}:
            return jsonify({
                "success": False,
                "error": "Choose litres or pieces for each material."
            }), 400

        try:
            quantity = float(item.get("quantity"))
            amount = float(item.get("amount"))

            if (
                not (0 < quantity <= 1_000_000)
                or not (0 <= amount <= 1_000_000_000)
            ):
                raise ValueError

        except (TypeError, ValueError):
            return jsonify({
                "success": False,
                "error": "Quantity must be positive and amount must be valid."
            }), 400

        cleaned_items.append({
            "material_name": material_name,
            "quantity": quantity,
            "unit": unit,
            "amount": amount
        })

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with get_db() as db:
            # Reuse the existing washing centre regardless of name case.
            db.execute("""
                INSERT INTO washing_centres (name, created_at)
                VALUES (?, ?)
                ON CONFLICT(name) DO NOTHING
            """, (centre_name, now))

            centre = db.execute("""
                SELECT id, name
                FROM washing_centres
                WHERE name = ? COLLATE NOCASE
            """, (centre_name,)).fetchone()

            cursor = db.execute("""
                INSERT INTO supply_entries (
                    centre_id, supply_date, created_at
                )
                VALUES (?, ?, ?)
            """, (centre["id"], supply_date, now))

            entry_id = cursor.lastrowid

            for item in cleaned_items:
                db.execute("""
                    INSERT INTO supply_items (
                        entry_id, material_name, quantity, unit, amount
                    )
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    entry_id,
                    item["material_name"],
                    item["quantity"],
                    item["unit"],
                    item["amount"]
                ))

        total = sum(item["amount"] for item in cleaned_items)

        return jsonify({
            "success": True,
            "message": "Shampoo supply saved successfully.",
            "customer_name": centre["name"],
            "entry_id": entry_id,
            "total_amount": total
        }), 201


    
    except Exception:
        app.logger.exception("Saving shampoo supply failed")
        return jsonify({
            "success": False,
            "error": "Could not save the shampoo supply. Please try again."
        }), 500



@app.route("/api/supplies/<int:entry_id>", methods=["DELETE"])
@login_required
def delete_supply(entry_id):
    try:
        with get_db() as db:
            # Check whether the supply entry exists.
            entry = db.execute(
                "SELECT id FROM supply_entries WHERE id = ?",
                (entry_id,)
            ).fetchone()

            if entry is None:
                return jsonify({
                    "success": False,
                    "error": "Supply entry not found."
                }), 404

            # Delete the materials first.
            db.execute(
                "DELETE FROM supply_items WHERE entry_id = ?",
                (entry_id,)
            )

            # Then delete the supply entry.
            db.execute(
                "DELETE FROM supply_entries WHERE id = ?",
                (entry_id,)
            )

        return jsonify({
            "success": True,
            "message": "Supply deleted successfully."
        })

    except Exception as error:
        app.logger.exception("Deleting supply failed")
        return jsonify({
            "success": False,
            "error": "Could not delete the supply. Please try again."
        }), 500


@app.route("/api/supplies/<int:entry_id>", methods=["GET"])
@login_required
def get_supply_entry(entry_id):
    with get_db() as db:
        entry = db.execute(
            """
            SELECT
                se.id,
                se.centre_id,
                wc.name AS centre_name,
                se.supply_date
            FROM supply_entries se
            JOIN washing_centres wc
                ON wc.id = se.centre_id
            WHERE se.id = ?
            """,
            (entry_id,)
        ).fetchone()

        if entry is None:
            return jsonify({
                "success": False,
                "error": "Supply entry not found."
            }), 404

        items = db.execute(
            """
            SELECT material_name, quantity, unit, amount
            FROM supply_items
            WHERE entry_id = ?
            ORDER BY id
            """,
            (entry_id,)
        ).fetchall()

        return jsonify({
            "success": True,
            "entry": {
                "id": entry["id"],
                "centre_id": entry["centre_id"],
                "centre_name": entry["centre_name"],
                "supply_date": entry["supply_date"],
                "items": [dict(item) for item in items]
            }
        })
# ==================================================
# 16. ERROR HANDLING
# ==================================================

@app.errorhandler(413)
def file_too_large(_error):
    return jsonify({
        "success": False,
        "error": "Image is too large. Maximum size is 20 MB."
    }), 413


# ==================================================
# 17. START SERVER
# ==================================================

if __name__ == "__main__":
    app.run(debug=True)
