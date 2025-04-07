import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configuration class to store app settings
class Config:
    # API settings
    API_KEY = os.environ.get('ODDS_API_KEY')
    SPORT = "basketball_nba"
    REGIONS = "us"
    MARKETS_MAIN = "h2h,spreads,totals"
    MARKETS_PROPS = "player_points,player_assists,player_rebounds"
    ODDS_FORMAT = "american"
    
    # Flask settings
    DEBUG = os.environ.get('DEBUG', 'False').lower() in ('true', '1', 't')
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')