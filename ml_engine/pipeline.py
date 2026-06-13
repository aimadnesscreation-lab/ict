import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import joblib
from loguru import logger

class MLPipeline:
    def __init__(self, model_path: str = "ml_engine/models/trading_model.json"):
        self.model_path = model_path
        self.model = None

    def prepare_features(self, df_signals: pd.DataFrame) -> pd.DataFrame:
        """
        Convert raw signals and market state into features.
        """
        # Features from full.md: MSS, BOS, Liquidity Sweep, FVG Size, ATR, Volume, News
        # For now, we assume the input df already has these columns
        feature_cols = ["score", "news_sentiment", "atr", "volume", "mss", "sweep"]
        return df_signals[feature_cols]

    def train(self, X: pd.DataFrame, y: pd.Series):
        """
        Train the XGBoost model.
        """
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        self.model = xgb.XGBClassifier(
            n_estimators=100,
            learning_rate=0.05,
            max_depth=5,
            objective="binary:logistic"
        )
        
        logger.info("Starting model training...")
        self.model.fit(X_train, y_train)
        
        preds = self.model.predict(X_test)
        acc = accuracy_score(y_test, preds)
        logger.info(f"Training complete. Accuracy: {acc:.4f}")
        logger.info(f"Classification Report:\n{classification_report(y_test, preds)}")
        
        # Save model
        import os
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        self.model.save_model(self.model_path)

    def predict(self, X: pd.DataFrame) -> pd.Series:
        """
        Predict probability of win.
        """
        if self.model is None:
            if not os.path.exists(self.model_path):
                raise Exception("Model not trained yet.")
            self.model = xgb.XGBClassifier()
            self.model.load_model(self.model_path)
            
        return self.model.predict_proba(X)[:, 1]
