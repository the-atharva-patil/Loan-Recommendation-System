from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pickle
import pandas as pd
import os
import sys
from dotenv import load_dotenv
from typing import Any, Dict

# Load model + scaler + encoder (you must have saved them together in pickle)
with open("xgb_best_model.pkl", "rb") as f:
    model, scaler, feature_columns = pickle.load(f)

app = FastAPI(title="Loan Prediction API")

# CORS settings
origins = ["http://localhost:5173", "http://127.0.0.1:5173","https://loan-rag.vercel.app"]
app.add_middleware(
    CORSMiddleware,
    allow_origins= origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load env for RAG system
load_dotenv()

# Try to import the LoanRAGSystem from the sibling repo
try:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    rag_path = os.path.abspath(os.path.join(repo_root, '..', 'rag-loan-llm-model'))
    if not os.path.exists(rag_path):
        rag_path = os.path.abspath(os.path.join(repo_root, '..', 'RAG-model-for-loan'))
    vectorstore_path = os.path.abspath(os.path.join(rag_path, 'vectorstore', 'db_faiss'))
    if rag_path not in sys.path:
        sys.path.insert(0, rag_path)
    from loan_rag_enhanced import LoanRAGSystem
    try:
        rag_system = LoanRAGSystem(vectorstore_path=vectorstore_path)
    except Exception:
        # lazy initialize on first call if initialization fails here
        rag_system = None
except Exception:
    rag_system = None

# Input schema
class LoanRequest(BaseModel):
    age: float
    income: float
    creditScore: float
    maritalStatus: str
    purpose: str

@app.post("/predict")
def predict_loan(data: LoanRequest):
    # Convert input to DataFrame
    df = pd.DataFrame([{
        "Age": data.age,
        "Income_Lakhs": data.income,
        "Credit_Score": data.creditScore,
        "Marital_Status": data.maritalStatus,
        "Purpose": data.purpose
    }])

    # One-hot encode to match training
    df_encoded = pd.get_dummies(df)
    df_encoded = df_encoded.reindex(columns=feature_columns, fill_value=0)

    # Scale numerical features
    df_scaled = scaler.transform(df_encoded)

    # Predict
    prediction = model.predict(df_scaled)[0]
    return {"predictedLoanAmount": round(float(prediction), 2)}


@app.post("/rag/query")
def rag_query(payload: Dict[str, Any]):
    """Proxy endpoint that runs the RAG query using the LoanRAGSystem from the other repo.

    Expects JSON: { "query": "user query string" }
    Returns the LoanRAGSystem.query(...) result.
    """
    global rag_system
    query = payload.get('query') or payload.get('q')
    if not query:
        return {"success": False, "error": "Missing 'query' in request"}

    # initialize rag_system lazily if needed
    if rag_system is None:
        try:
            from loan_rag_enhanced import LoanRAGSystem
            repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
            rag_path = os.path.abspath(os.path.join(repo_root, '..', 'rag-loan-llm-model'))
            if not os.path.exists(rag_path):
                rag_path = os.path.abspath(os.path.join(repo_root, '..', 'RAG-model-for-loan'))
            vectorstore_path = os.path.abspath(os.path.join(rag_path, 'vectorstore', 'db_faiss'))
            rag_system = LoanRAGSystem(vectorstore_path=vectorstore_path)
        except Exception as e:
            return {"success": False, "error": f"Failed initializing RAG system: {e}"}

    try:
        result = rag_system.query(query)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}
