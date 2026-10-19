# Vehicle Collection Website

A starter website for phone and laptop use: private login, camera/photo upload, number-plate OCR, editable collection rows, Google Pay/PhonePe/Cash labels, payment totals, and CSV export.

## Important limitations
- The scanner uses Tesseract OCR and basic image processing. It is a prototype, not a guaranteed automatic number-plate recognition system. Always verify the detected plate before saving. For reliable ANPR in different lighting/angles, replace `read_plate()` with a dedicated plate-detection model.
- Google Pay and PhonePe are payment-method labels only. This app does not verify UPI payments or collect money.
- Photos and vehicle numbers are sensitive. Use only for a lawful purpose, tell people as required by local rules, restrict access, and keep the website private.
- SQLite and uploaded photos are saved under `DATA_DIR`. Online hosting must have a persistent disk mounted at that path or records/photos may be lost during redeploy/restart.

## Run on Windows (beginner steps)
1. Install Python 3.11 or newer from https://www.python.org/downloads/ . During installation, tick **Add Python to PATH**.
2. Install Tesseract OCR for Windows. After installing, if Tesseract is not on PATH, open `app.py` and add this line after the imports:
   `pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"`
3. Extract this ZIP to a folder, then open that folder in VS Code.
4. Open Terminal in VS Code and run:
   ```powershell
   py -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   copy .env.example .env
   ```
5. Edit `.env`. Set a long unique `SECRET_KEY`, `ADMIN_USERNAME`, and `ADMIN_PASSWORD`. Never publish this file or share your password.
6. Start the app:
   ```powershell
   python app.py
   ```
7. On your laptop, visit `http://127.0.0.1:5000`. For phone testing on the same Wi-Fi, use the laptop's local IP and port 5000. Local testing is not online hosting.

## Deploy online using Render (Docker)
1. Create a private GitHub repository and upload the project files. Do **not** upload `.env`, passwords, `data/`, or vehicle photos.
2. Create a Render account and choose **New → Web Service**, connect the repository, and select Docker as the runtime.
3. Add environment variables in Render:
   - `SECRET_KEY`: long random secret
   - `ADMIN_USERNAME`: your chosen login
   - `ADMIN_PASSWORD`: a long unique password
   - `COOKIE_SECURE`: `1`
4. Attach a **persistent disk** to the service mounted at `/var/data`. Choose a plan that supports persistent disks and check its current price/limits before deploying. The Dockerfile stores SQLite and photos under `/var/data`.
5. Deploy. Open the HTTPS URL Render provides, sign in, and test photo capture, save/edit/delete, totals, and CSV export from both phone and laptop.
6. Keep the repository private and never commit `.env` or customer photos. Set a backup routine for `/var/data`.

## If OCR does not work
- Use a clear, straight-on image with the number plate filling much of the photo.
- Avoid glare, night blur, and extreme angles.
- Manually correct the plate in the vehicle number field.
- OCR support depends on image quality and Tesseract language/data availability.

## Data backup
Stop writing new records briefly, then back up the SQLite database and `uploads/` directory together. Keep backups in a private location. Test restoring a backup before relying on this for business records.
