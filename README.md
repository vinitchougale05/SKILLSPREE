# SkillSpree

SkillSpree is a Personalized Education Platform that provides tailored learning goals, dynamically generated assessments, and personalized course recommendations.

## New Project Structure

The project has been refactored into a scalable Flask Application Factory architecture:

```
.
├── .env.example          # Environment variables template
├── README.md             # Project documentation
├── app/                  # Main application package
│   ├── __init__.py       # App factory and configuration
│   ├── main/             # Main blueprint
│   │   ├── __init__.py   # Blueprint initialization
│   │   └── routes.py     # All application routes
│   ├── ml_utils.py       # Gemini AI integration logic
│   ├── templates/        # Jinja HTML templates
│   └── youtube_utils.py  # YouTube API logic
├── config.py             # Centralized settings
├── requirements.txt      # Pinned project dependencies
└── run.py                # Application entry point
```

## Setup Instructions

1. **Clone the repository and enter the directory**:
   ```bash
   # cd SKILLSPREE
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows, use `venv\Scripts\activate`
   ```

3. **Install the dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables**:
   Copy `.env.example` to a new file named `.env` and fill in your details:
   ```bash
   cp .env.example .env
   ```
   *Note: Update `MONGO_URI` if your MongoDB isn't running on localhost, and set your own `GOOGLE_API_KEY` for AI features and `SECRET_KEY`.*

5. **Start the application**:
   Run the Flask server using the new entry point:
   ```bash
   python run.py
   ```

## Using `.env`
The application now uses `python-dotenv` to manage secrets. Ensure that you have created the `.env` file and configured it with `SECRET_KEY`, `MONGO_URI`, `DB_NAME`, and `GOOGLE_API_KEY`. These keys are loaded automatically by `config.py` upon initialization.

## How to run with python run.py
Simply execute `python run.py` from the root of the directory. The application factory `create_app()` will initialize Flask, register the blueprints, connect to MongoDB, and start the development server on `0.0.0.0:5000`.