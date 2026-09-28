import torch
import numpy as np
from flask import Flask, render_template, request
from transformers import DistilBertTokenizerFast, DistilBertForSequenceClassification
import re
from bs4 import BeautifulSoup
import os

# --- 1. CONFIGURATION ---
MODEL_PATH = './veritas_engine_model'
MAX_LEN = 512
app = Flask(__name__)

# --- 2. MODEL LOADING ---
# Load the model and tokenizer only once when the application starts
def load_model():
    try:
        # Check for GPU, default to CPU
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Server using device: {device}")
        
        # Load the saved artifacts
        tokenizer = DistilBertTokenizerFast.from_pretrained(MODEL_PATH)
        model = DistilBertForSequenceClassification.from_pretrained(MODEL_PATH)
        model.to(device)
        model.eval() # Set model to evaluation mode
        return tokenizer, model, device
    except Exception as e:
        print(f"FATAL ERROR LOADING MODEL: {e}")
        return None, None, None

tokenizer, model, device = load_model()

# --- 3. INFERENCE FUNCTION ---
def preprocess_and_predict(text):
    if model is None:
        return "Error", 0.0, "Model Not Loaded"

    # --- A. CLEANING (MUST be identical to the training cleaning function) ---
    def clean_text_for_inference(text):
        text = str(text).lower()
        try:
            soup = BeautifulSoup(text, 'html.parser')
            text = soup.get_text()
        except:
            text = re.sub(r'<.*?>', ' ', text)
        
        # Replace placeholders and remove metadata
        text = re.sub(r'http\S+|www\S+|https\S+', '[URL]', text)
        text = re.sub(r'\S*@\S*\s?', '[EMAIL_ADDRESS]', text)
        text = re.sub(r'from : .* to : .* subject : ', ' ', text)
        text = re.sub(r'forwarded by .* on .*', ' ', text)
        text = re.sub(r'\( see attached file : \S* \. xls \)', '[ATTACHMENT]', text)
        text = re.sub(r'\S* \. xls', '[ATTACHMENT]', text)
        text = re.sub(r'-{3,}', ' ', text)
        text = re.sub(r'[^a-zA-Z\s\[\]]', ' ', text)
        text = re.sub('\s+', ' ', text).strip()
        return text

    cleaned_text = clean_text_for_inference(text)
    
    # --- B. TOKENIZATION & PREDICTION ---
    encoding = tokenizer(
        cleaned_text,
        max_length=MAX_LEN,
        truncation=True,
        padding='max_length',
        return_tensors='pt'
    )
    
    input_ids = encoding['input_ids'].to(device)
    attention_mask = encoding['attention_mask'].to(device)
    
    with torch.no_grad():
        outputs = model(input_ids=input_ids, attention_mask=attention_mask)
        
    logits = outputs.logits
    probs = torch.softmax(logits, dim=1).cpu().numpy()[0]
    
    prediction_index = np.argmax(probs)
    result_label = "PHISHING" if prediction_index == 1 else "LEGITIMATE"
    confidence = probs[prediction_index] * 100 
    
    return result_label, confidence, cleaned_text

# --- 4. FLASK ROUTES ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        email_content = request.form['email_content']
        
        # Get the prediction
        label, confidence, _ = preprocess_and_predict(email_content)
        
        # Pass results back to the HTML template
        return render_template('index.html', 
                               result_label=label, 
                               confidence=f"{confidence:.2f}%",
                               email_content=email_content)
    
    # Initial page load
    return render_template('index.html', result_label=None, confidence=None)

# --- 5. RUN THE APP ---
if __name__ == '__main__':
    # You must have Flask installed: pip install flask
    app.run(debug=True)