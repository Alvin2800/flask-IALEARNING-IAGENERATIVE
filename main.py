from flask import Flask, request, jsonify
from datetime import datetime
import pandas as pd
import os
import mysql.connector
from sklearn.ensemble import IsolationForest
import google.generativeai as genai

app = Flask(__name__)

# ==========================================
# CONFIG MYSQL RAILWAY
# ==========================================

db_config = {
    "host": os.getenv("MYSQLHOST"),
    "user": os.getenv("MYSQLUSER"),
    "password": os.getenv("MYSQLPASSWORD"),
    "database": os.getenv("MYSQLDATABASE"),
    "port": int(os.getenv("MYSQLPORT", 3306))
}


def db_connection():
    return mysql.connector.connect(**db_config)


# ==========================================
# INITIALISATION DATABASE
# ==========================================

def init_db():

    try:

        conn = db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fuel_measurements(

                id INT AUTO_INCREMENT PRIMARY KEY,

                timestamp DATETIME,

                device_id VARCHAR(50),

                fuel_level FLOAT

            )
        """)

        conn.commit()

        cursor.close()
        conn.close()

        print("TABLE fuel_measurements OK", flush=True)

    except Exception as e:

        print("Erreur création table :", e, flush=True)


init_db()

# ==========================================
# ROUTE HOME
# ==========================================

@app.route("/")
def home():
    return "API IS WORKING"


# ==========================================
# TEST DATABASE
# ==========================================

@app.route("/test_db")
def test_db():

    try:

        conn = db_connection()

        cursor = conn.cursor()

        cursor.execute("SELECT 1")

        result = cursor.fetchone()

        cursor.close()
        conn.close()

        return jsonify({
            "status": "success",
            "message": "Connexion SQL OK",
            "result": result
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ==========================================
# INSERT DATA
# ==========================================

@app.route("/data")
def data():

    try:

        device_id = request.args.get(
            "device_id",
            "pico_001"
        )

        fuel_level = request.args.get("fuel_level")

        fuel_level = float(fuel_level)

        conn = db_connection()

        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO fuel_measurements(
                timestamp,
                device_id,
                fuel_level
            )
            VALUES(%s,%s,%s)
        """, (

            datetime.now(),
            device_id,
            fuel_level

        ))

        conn.commit()

        cursor.close()
        conn.close()

        return jsonify({

            "status": "success",

            "device_id": device_id,

            "fuel_level": fuel_level

        })

    except Exception as e:

        return jsonify({

            "status": "error",

            "message": str(e)

        }), 500


# ==========================================
# LOGS
# ==========================================

@app.route("/logs")
def logs():

    try:

        conn = db_connection()

        cursor = conn.cursor()

        cursor.execute("""
            SELECT *
            FROM fuel_measurements
            ORDER BY timestamp DESC
            LIMIT 50
        """)

        data = cursor.fetchall()

        cursor.close()
        conn.close()

        return jsonify(data)

    except Exception as e:

        return jsonify({

            "status": "error",

            "message": str(e)

        }), 500


# ==========================================
# IA ANALYSE
# ==========================================

@app.route("/analyse")
def analyse():

    try:

        conn = db_connection()

        query = """
            SELECT *
            FROM fuel_measurements
            ORDER BY timestamp
            LIMIT 50
        """

        df = pd.read_sql(query, conn)

        conn.close()

        if len(df) < 5:

            return jsonify({

                "status": "error",

                "message": "Pas assez de données"

            }), 500

        model = IsolationForest(

            contamination=0.15,

            random_state=42

        )

        df["anormaly"] = model.fit_predict(
            df[["fuel_level"]]
        )

        resultat = []

        for _, row in df.iterrows():

            resultat.append({

                "id": int(row["id"]),

                "timestamp": str(row["timestamp"]),

                "device_id": row["device_id"],

                "fuel_level": float(row["fuel_level"]),

                "status": "ANOMALIE"
                if row["anormaly"] == -1
                else "NORMAL"

            })

        return jsonify(resultat)

    except Exception as e:

        return jsonify({

            "status": "error",

            "message": str(e)

        }), 500


# ==========================================
# IA GENERATIVE GEMINI
# ==========================================

@app.route("/ai_report")
def ai_report():

    try:

        api_key = os.getenv("GEMINI_API_KEY")

        if not api_key:

            return jsonify({

                "status": "error",

                "message": "GEMINI_API_KEY manquante"

            }), 500

        genai.configure(api_key=api_key)

        start_date = request.args.get("start_date")

        end_date = request.args.get("end_date")

        conn = db_connection()

        # ==========================
        # REQUETE SQL
        # ==========================

        if start_date and end_date:

            query = """
                SELECT *
                FROM fuel_measurements
                WHERE DATE(timestamp)
                BETWEEN %s AND %s
                ORDER BY timestamp ASC
            """

            df = pd.read_sql(
                query,
                conn,
                params=(start_date, end_date)
            )

        else:

            query = """
                SELECT *
                FROM fuel_measurements
                ORDER BY timestamp ASC
            """

            df = pd.read_sql(query, conn)

        conn.close()

        # ==========================
        # VERIFICATION DATA
        # ==========================

        if len(df) < 5:

            return jsonify({

                "status": "error",

                "message": "Pas assez de données"

            }), 500

        # ==========================
        # IA ISOLATION FOREST
        # ==========================

        model_iforest = IsolationForest(

            contamination=0.15,

            random_state=42

        )

        df["anormaly"] = model_iforest.fit_predict(
            df[["fuel_level"]]
        )

        anomalies = df[
            df["anormaly"] == -1
        ]

        # ==========================
        # SI AUCUNE ANOMALIE
        # ==========================

        if anomalies.empty:

            return jsonify({

                "status": "success",

                "report":
                "Aucune anomalie détectée sur la période."

            })

        # ==========================
        # CREATION TEXTE ANOMALIES
        # ==========================

        anomaly_text = ""

        for _, row in anomalies.iterrows():

            anomaly_text += f"""

Horodatage : {row['timestamp']}

Appareil : {row['device_id']}

Niveau carburant : {row['fuel_level']} %

-----------------------------------

"""

        # ==========================
        # TEXTE PERIODE
        # ==========================

        if start_date and end_date:

            periode_text = f"""
Période analysée :
du {start_date} au {end_date}
"""

        else:

            periode_text = """
Période analysée :
toutes les données disponibles
"""

        # ==========================
        # PROMPT GEMINI
        # ==========================

        prompt = f"""
Tu es un assistant industriel spécialisé en IoT,
supervision carburant,
détection d'anomalies
et maintenance intelligente.

{periode_text}

Voici les anomalies détectées :

{anomaly_text}

Rédige un rapport court en français
avec cette structure :

1. Résumé de la situation

2. Interprétation possible

3. Recommandation technique

Le rapport doit être :
- clair
- professionnel
- facile à comprendre
"""

        # ==========================
        # GEMINI
        # ==========================

        model_gemini = genai.GenerativeModel(
            "gemini-2.5-flash"
        )

        reponse = model_gemini.generate_content(
            prompt
        )

        # ==========================
        # RETOUR API
        # ==========================

        return jsonify({

            "status": "success",

            "start_date": start_date,

            "end_date": end_date,

            "report": reponse.text

        })

    except Exception as e:

        return jsonify({

            "status": "error",

            "message": str(e)

        }), 500


# ==========================================
# LANCEMENT APP
# ==========================================

if __name__ == "__main__":

    app.run(

        host="0.0.0.0",

        port=int(os.getenv("PORT", 5000))

    )
