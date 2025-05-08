import os
from io import StringIO
import csv
import pandas as pd
from datetime import date
from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from flask_talisman import Talisman
import magic
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# Configuración de seguridad HTTPS
talisman = Talisman(
    app,
    content_security_policy=None,
    force_https=os.environ.get('ENV') == 'production'
)

# Configuración para proxy inverso de Render
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Configuraciones de la aplicación
app.config['MAX_CONTENT_LENGTH'] = 10 * (1024**2)  # 10 MiB
app.config['ALLOWED_EXTENSIONS'] = {'txt', 'csv', 'json'}
ALLOWED_MIME_TYPES = {'text/plain', 'text/csv', 'application/json'}

def validar_file(archivo):
    try:
        # Leer solo los primeros bytes para MIME type
        header = archivo.stream.read(2048)
        archivo.stream.seek(0)
        mime_type = magic.from_buffer(header, mime=True)

        # Verificar extensión
        filename = secure_filename(archivo.filename)

        if '.' not in filename:
            return False

        extension = filename.rsplit('.', 1)[1].lower()
        return (
            extension in app.config['ALLOWED_EXTENSIONS'] and
            mime_type in ['ALLOWED_MIME_TYPES']
        )
    except Exception as e:
        app.logger.error(f'Error validación: {str(e)}')
        return False

def convert_size(size):
    unit = str()
    if size == 0:
        return "0B"

    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    for unit in units:
        if size < 1024:
            break
        size /= 1024
    return f"{size:.2f} {unit}"

def detect_delimiter(csv_content):
    # Analizar las primeras líneas para detectar el delimitador
    sniffer = csv.Sniffer()
    dialect = sniffer.sniff(csv_content.split("\n")[0])
    return dialect.delimiter

def show_csv_data(file, filename):
    try:
        csv_content = file.read().decode("utf-8")
        delimiter = detect_delimiter(csv_content)
        
        # Leer CSV y convertir NaN a None
        df = pd.read_csv(
            StringIO(csv_content),
            delimiter=delimiter,
        )
        
        # Convertir columnas numéricas a Int64 (admite nulos)
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
        
        # Preparar datos para la plantilla
        preview_data = df.head(10).replace({pd.NA: None}).values.tolist()
        
        stats = {
            "delimiter": delimiter,
            "column_types": df.dtypes.astype(str).to_dict(),
            "unique_counts": df.nunique().to_dict(),
            "null_counts": df.isnull().sum().to_dict(),
            "total_non_null": (len(df) - df.isnull().sum()).to_dict()
        }
        
        return render_template(
            "result_csv.html",
            filename=filename,
            headers=df.columns.tolist(),
            preview_data=preview_data,
            stats=stats
        )
        
    except Exception as e:
        app.logger.error(f"Error procesando CSV: {str(e)}")
        flash("Error al analizar el archivo CSV")
        return redirect(url_for("upload_file"))

@app.route('/', methods=['GET', 'POST'])

def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No se encontró el archivo')

            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash('No se seleccionó ningún archivo')
            return redirect(request.url)

        if file:
            filename = secure_filename(str(file.filename))
            file_type = file.mimetype

            # Validación MIME type estricta
            if file_type not in ALLOWED_MIME_TYPES:
                flash('Tipo de archivo no permitido')
                return redirect(request.url)

            # Calcular tamaño
            file.seek(0, os.SEEK_END)
            size_bytes = file.tell()
            file.seek(0)

            try:
                if file_type == 'text/csv':
                    return show_csv_data(file, filename)
                else:
                    datefile = date.today()
                    content = file.read().decode('UTF-8')
                    lines = len(content.splitlines())
                    words = len(content.split())
                    characters = len(content)

                    return render_template('result.html',
                                        filename=filename,
                                        file_type=file_type,
                                        date=datefile,
                                        size=convert_size(size_bytes),
                                        lines=lines,
                                        words=words,
                                        characters=characters)
            except UnicodeDecodeError:
                flash('El archivo no es texto válido')
                return redirect(request.url)
            except Exception as e:
                flash('Error procesando archivo')
                app.logger.error(f'Error: {str(e)}')
                return redirect(request.url)

    return render_template('upload.html')

if __name__ == '__main__':
    if os.environ.get('ENV') == 'production':
        from waitress import serve
        serve(app, host='0.0.0.0', port=8080)
    else:
        app.run(host='0.0.0.0', port=8080, debug=True)
