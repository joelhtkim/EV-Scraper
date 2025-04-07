from flask import Flask, render_template, request
import requests
import os

# Use compatible Flask version specified in requirements.txt
app = Flask(__name__, template_folder='../templates')

# Configuration directly in the file for simplicity
API_KEY = os.environ.get('ODDS_API_KEY')
SPORT = "basketball_nba"
REGIONS = "us"
MARKETS_MAIN = "h2h,spreads,totals"
MARKETS_PROPS = "player_points,player_assists,player_rebounds"
ODDS_FORMAT = "american"

def american_to_decimal(american_odds):
    """Convert American odds to decimal."""
    if american_odds < 0:
        return 1 + (100 / abs(american_odds))
    else:
        return 1 + (american_odds / 100)

def decimal_to_american(decimal_odds):
    """Convert decimal odds to American."""
    if decimal_odds <= 1.0:
        return 0  # Just a fallback
    elif decimal_odds < 2.0:
        return int(-100 / (decimal_odds - 1))
    else:
        return int((decimal_odds - 1) * 100)

def remove_vig(decimal_odds_list):
    """Return fair decimal odds list with the vig removed."""
    implied_probs = [1/o for o in decimal_odds_list if o > 0]
    total_implied = sum(implied_probs)
    if total_implied <= 0:
        return decimal_odds_list
    fair_odds = []
    for p in implied_probs:
        fair_prob = p / total_implied
        fair_odds.append(1 / fair_prob)
    return fair_odds

def get_standard_odds_data():
    """Fetch standard (main) markets for all NBA events."""
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": MARKETS_MAIN,
        "oddsFormat": ODDS_FORMAT,
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()

def get_props_odds_data(event_id):
    """Fetch player props for one event."""
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT}/events/{event_id}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": REGIONS,
        "markets": MARKETS_PROPS,
        "oddsFormat": ODDS_FORMAT,
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json()

def build_spread_data(away_team, home_team, bookmakers):
    """
    For the "spreads" market only, gather each bookmaker's line for 
    (away_team) and (home_team). Then compute "best line," "no-vig" lines, 
    "hold," etc. 
    """
    away_lines = {}
    home_lines = {}

    # Collect all lines from all books
    for bookmaker in bookmakers:
        book_name = bookmaker.get("title")
        for market in bookmaker.get("markets", []):
            if market.get("key") == "spreads":
                for outcome in market.get("outcomes", []):
                    if outcome["name"] == away_team:
                        away_price = outcome["price"]
                        away_point = outcome.get("point")
                        away_lines[book_name] = (away_point, away_price)
                    elif outcome["name"] == home_team:
                        home_price = outcome["price"]
                        home_point = outcome.get("point")
                        home_lines[book_name] = (home_point, home_price)

    # Compute "best line" for each side
    best_away = pick_best_line(away_lines)
    best_home = pick_best_line(home_lines)

    # Compute hold
    hold_value = compute_hold_percent(away_lines, home_lines)

    # Convert lines into a nicer dict
    away_display = {}
    for b, (pt, price) in away_lines.items():
        away_display[b] = format_line(pt, price)

    home_display = {}
    for b, (pt, price) in home_lines.items():
        home_display[b] = format_line(pt, price)

    return {
        "away": {
            "best_line": format_line(*best_away) if best_away else "",
            "book_lines": away_display
        },
        "home": {
            "best_line": format_line(*best_home) if best_home else "",
            "book_lines": home_display
        },
        "hold": hold_value
    }

def pick_best_line(lines_dict):
    """
    lines_dict = { "BookName": (spread_point, american_price), ... }
    We'll define "best" by largest decimal price. 
    Returns a tuple (spread_point, american_price) or None if no lines.
    """
    best_tuple = None
    best_decimal = 0.0
    for book_name, (pt, price) in lines_dict.items():
        dec = american_to_decimal(price)
        if dec > best_decimal:
            best_decimal = dec
            best_tuple = (pt, price)
    return best_tuple

def compute_hold_percent(away_lines, home_lines):
    """
    Very rough example: take the away *average decimal odds* and home 
    *average decimal odds*, sum implied probabilities, see how far above 1.0.
    """
    away_decimal_list = []
    for pt, price in away_lines.values():
        away_decimal_list.append(american_to_decimal(price))
    home_decimal_list = []
    for pt, price in home_lines.values():
        home_decimal_list.append(american_to_decimal(price))

    # Average decimal for away, home
    away_dec = sum(away_decimal_list)/len(away_decimal_list) if away_decimal_list else 0
    home_dec = sum(home_decimal_list)/len(home_decimal_list) if home_decimal_list else 0

    # Implied probabilities
    away_imp = 1/away_dec if away_dec > 0 else 0
    home_imp = 1/home_dec if home_dec > 0 else 0
    sum_imp = away_imp + home_imp

    # hold% = sum_imp - 1, as a percentage
    hold_pct = (sum_imp - 1.0)*100 if sum_imp > 0 else 0
    return round(hold_pct, 2)

def format_line(spread_point, american_price):
    """Helper to return something like '-1.5 -110' for display."""
    return f"{spread_point} ({american_price:+})" if american_price else ""

def get_props_data_formatted(event_id):
    """Fetch and format player props for an event."""
    try:
        # Get the event odds for player props
        props_data = get_props_odds_data(event_id)
        
        # Initialize formatted props structure
        formatted_props = {
            'points': {},
            'assists': {},
            'rebounds': {}
        }
        
        # Process bookmakers from the props data
        bookmakers = props_data.get('bookmakers', [])
        
        for bookmaker in bookmakers:
            book_name = bookmaker.get('title')
            
            for market in bookmaker.get('markets', []):
                market_key = market.get('key')
                if market_key not in ['player_points', 'player_assists', 'player_rebounds']:
                    continue
                    
                prop_type = market_key.split('_')[1]  # points, assists, or rebounds
                
                # Group outcomes by player (using description field)
                player_outcomes = {}
                for outcome in market.get('outcomes', []):
                    player_name = outcome.get('description')
                    if not player_name:
                        continue
                        
                    if player_name not in player_outcomes:
                        player_outcomes[player_name] = []
                    player_outcomes[player_name].append(outcome)
                
                # Process each player's over/under lines
                for player_name, outcomes in player_outcomes.items():
                    if player_name not in formatted_props[prop_type]:
                        formatted_props[prop_type][player_name] = {
                            'line': None,
                            'books': {}
                        }
                    
                    # Find the "Over" outcome to get the line
                    over_outcome = next((o for o in outcomes if o.get('name') == 'Over'), None)
                    if over_outcome:
                        point = over_outcome.get('point')
                        formatted_props[prop_type][player_name]['line'] = point
                        
                        # Store both over/under prices
                        under_outcome = next((o for o in outcomes if o.get('name') == 'Under'), None)
                        formatted_props[prop_type][player_name]['books'][book_name] = {
                            'point': point,
                            'over_price': over_outcome.get('price'),
                            'under_price': under_outcome.get('price') if under_outcome else None
                        }
        
        return formatted_props
    except requests.HTTPError as e:
        print(f"HTTP Error fetching props: {str(e)}")
        return {}
    except Exception as e:
        print(f"Error processing props: {str(e)}")
        return {}

def process_events():
    """Modified to include event IDs and commence times for props navigation."""
    standard_events = get_standard_odds_data()
    
    all_processed = []
    for event in standard_events:
        event_id = event.get("id")
        home_team = event.get("home_team")
        away_team = event.get("away_team")
        commence_time = event.get("commence_time", "")
        
        spread_data = build_spread_data(away_team, home_team, event.get("bookmakers", []))
        
        all_processed.append({
            "event_id": event_id,
            "away_team": away_team,
            "home_team": home_team,
            "commence_time": commence_time,
            "spread_data": spread_data,
        })
    
    return all_processed

@app.route('/', methods=['GET'])
def index():
    events_data = process_events()
    all_books = set()
    for ev in events_data:
        for side in ("away","home"):
            all_books.update(ev["spread_data"][side]["book_lines"].keys())
    all_books = sorted(list(all_books))
    
    return render_template("index.html", 
                         events=events_data, 
                         all_books=all_books,
                         active_tab="main")

@app.route('/props/<event_id>', methods=['GET'])
def props(event_id):
    # Get basic event info
    events_data = process_events()
    event = next((e for e in events_data if e["event_id"] == event_id), None)
    
    if not event:
        return "Event not found", 404
    
    # Get props data
    props_data = get_props_data_formatted(event_id)
    
    # Get all books that have props
    props_books = set()
    for prop_type in props_data.values():
        for player_data in prop_type.values():
            props_books.update(player_data['books'].keys())
    props_books = sorted(list(props_books))
    
    return render_template("props.html",
                         event=event,
                         props_data=props_data,
                         all_books=props_books,
                         active_tab="props")

# Special handler for Vercel
def handler(event, context):
    return app(event, context)

# Local development server
if __name__ == "__main__":
    app.run(debug=True)