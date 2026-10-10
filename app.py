"""Frontend server only. Replace extract_text with your backend pipeline."""
from flask import Flask, jsonify, render_template

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024 + 64 * 1024

@app.get('/')
def index():
    return render_template('index.html')

@app.post('/api/extract-text')
def extract_text():
    return jsonify(error='Text reconstruction is not implemented yet. Connect your OCR, text removal and background repair pipeline to POST /api/extract-text.'), 501

@app.post('/api/edit-text')
def edit_text():
    return jsonify(error='AI text editing is unavailable. Connect your instruction interpreter to POST /api/edit-text. No text layers were changed.'), 501

@app.errorhandler(413)
def too_large(_error):
    return jsonify(error='The uploaded image exceeds the 20 MB limit.'), 413

if __name__ == '__main__':
    app.run()
