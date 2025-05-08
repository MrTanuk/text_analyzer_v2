import os
from io import StringIO
import csv
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify
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
app.config['ALLOWED_EXTENSIONS'] = {'txt', 'csv'}
ALLOWED_MIME_TYPES = {'text/plain', 'text/csv'}
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

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
                mime_type in ALLOWED_MIME_TYPES
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

def show_txt_data(file, filename):
    try:
        content = file.read().decode('utf-8')
        
        # Guardar el archivo en la carpeta uploads
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
            
        return render_template('result_txt.html',
                            filename=filename,
                            content=content,
                            size=convert_size(len(content)),
                            lines=len(content.splitlines()),
                            words=len(content.split()),
                            characters=len(content))
    except Exception as e:
        flash('Error procesando archivo de texto')
        return redirect(url_for('upload_file'))

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

            try:
                if file_type == 'text/csv':
                    return show_csv_data(file, filename)
                else:  # TXT
                    return show_txt_data(file, filename)

            except UnicodeDecodeError:
                flash('El archivo no es texto válido')
                return redirect(request.url)
            except Exception as e:
                flash('Error procesando archivo')
                app.logger.error(f'Error: {str(e)}')
                return redirect(request.url)

    return render_template('upload.html')

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        filename,
        as_attachment=True
    )

@app.route('/save_txt', methods=['POST'])
def save_txt():
    try:
        # Verificar si se recibieron datos JSON
        if not request.is_json:
            return jsonify({"success": False, "error": "Solicitud debe ser JSON"}), 400
        
        data = request.get_json()
        filename = secure_filename(data.get('filename'))
        content = data.get('content')
        
        if not filename or content is None:
            return jsonify({"success": False, "error": "Datos incompletos"}), 400
        
        # Guardar el archivo
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return jsonify({"success": True})
    
    except Exception as e:
        app.logger.error(f"Error al guardar TXT: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/save_csv', methods=['POST'])
def save_csv():
    try:
        data = request.json
        filename = secure_filename(data['filename'])
        delimiter = data['delimiter']
        
        # Crear DataFrame desde los datos editados
        df = pd.DataFrame(data['data'])
        
        # Guardar con el delimitador original
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        df.to_csv(filepath, sep=delimiter, index=False)
        
        return jsonify(success=True)
    
    except Exception as e:
        app.logger.error(f"Error guardando CSV: {str(e)}")
        return jsonify(success=False, error=str(e)), 500

if __name__ == '__main__':
    if os.environ.get('ENV') == 'production':
        from waitress import serve
        serve(app, host='0.0.0.0', port=8080)
    else:
        app.run(host='0.0.0.0', port=8080, debug=True)
