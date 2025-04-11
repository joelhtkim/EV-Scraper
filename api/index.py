from flask import Flask, render_template, request
import os
import requests

app = Flask(__name__, template_folder='../templates')

# Configuration directly in the file for simplicity
API_KEY = os.environ.get('ODDS_API_KEY')
SPORT = "basketball_nba"
REGIONS = "us"
MARKETS_MAIN = "h2h,spreads,totals"
MARKETS_PROPS = "player_points,player_assists,player_rebounds"
ODDS_FORMAT = "american"


def calculate_ev(odds):
    """Calculate implied probability from American odds."""
    if odds > 0:
        implied_probability = 100 / (odds + 100)
    else:
        implied_probability = abs(odds) / (abs(odds) + 100)
    return implied_probability

def american_to_decimal(american_odds):
    """Convert American odds to decimal."""
    if american_odds < 0:
        return 1 + (100 / abs(american_odds))
    else:
        return 1 + (american_odds / 100)

def decimal_to_american(decimal_odds):
    """Convert decimal odds to American format."""
    if decimal_odds <= 1.0:
        return 0  # Just a fallback
    elif decimal_odds < 2.0:
        return int(-100 / (decimal_odds - 1))
    else:
        return int((decimal_odds - 1) * 100)

def calculate_positive_ev(lines_dict):
    """
    Calculate +EV opportunities from a set of lines.
    
    Args:
        lines_dict: Dictionary of bookmaker lines in format {bookmaker: odds}
        
    Returns:
        Dictionary with EV data
    """
    if not lines_dict or len(lines_dict) <= 1:
        return None
    
    # Find the best line (highest decimal odds)
    best_bookmaker = None
    best_american_odds = None
    best_decimal_odds = 0
    
    # Calculate average implied probability
    total_probability = 0
    valid_books = 0
    all_implied_probs = {}
    all_decimal_odds = []
    
    # First pass - collect data
    for bookmaker, odds in lines_dict.items():
        if odds is None:
            continue
        
        # Convert to int if it's a string with +/- prefix
        if isinstance(odds, str):
            try:
                odds = int(odds)
            except ValueError:
                continue
        
        # Calculate decimal odds
        decimal_odds = american_to_decimal(odds)
        all_decimal_odds.append(decimal_odds)
        
        # Track best odds
        if decimal_odds > best_decimal_odds:
            best_decimal_odds = decimal_odds
            best_american_odds = odds
            best_bookmaker = bookmaker
        
        # Calculate implied probability
        implied_prob = calculate_ev(odds)
        all_implied_probs[bookmaker] = implied_prob
        
        # Add to totals
        total_probability += implied_prob
        valid_books += 1
    
    if valid_books <= 1:
        return None
        
    # Get average implied probability
    avg_probability = total_probability / valid_books
    
    # Calculate variance in the odds (as a measure of market agreement)
    import statistics
    odds_variance = statistics.stdev(all_decimal_odds) if len(all_decimal_odds) > 1 else 0
    
    # Calculate average American odds
    avg_decimal = sum(all_decimal_odds) / len(all_decimal_odds)
    avg_american = decimal_to_american(avg_decimal)
    
    # Calculate individual EV for each book and fair odds
    individual_ev = {}
    fair_odds = {}
    for bookmaker, odds in lines_dict.items():
        if odds is None:
            continue
            
        if isinstance(odds, str):
            try:
                odds = int(odds)
            except ValueError:
                continue
                
        # Calculate EV based on this book's odds vs market average
        decimal_odds = american_to_decimal(odds)
        individual_ev[bookmaker] = (decimal_odds * avg_probability - 1) * 100
        
        # Calculate fair odds based on market average (excluding this book)
        other_books_avg = (total_probability - all_implied_probs[bookmaker]) / (valid_books - 1) if valid_books > 1 else avg_probability
        fair_decimal = 1 / other_books_avg if other_books_avg > 0 else 0
        fair_odds[bookmaker] = decimal_to_american(fair_decimal)
    
    # Calculate overall EV using the best line against average probability
    ev_percentage = (best_decimal_odds * avg_probability - 1) * 100
    
    return {
        'best_book': best_bookmaker,
        'best_odds': best_american_odds,
        'all_odds': lines_dict,
        'implied_probabilities': all_implied_probs,
        'individual_ev': individual_ev,
        'fair_odds': fair_odds,
        'avg_implied_probability': avg_probability,
        'avg_american_odds': avg_american,
        'ev_percentage': round(ev_percentage, 2),
        'odds_variance': odds_variance,
        'markets': valid_books
    }

def find_ev_opportunities(events_data, min_ev_threshold=0):
    """
    Find positive EV opportunities across events for both game spreads and player props.
    
    Args:
        events_data: List of event dictionaries
        min_ev_threshold: Minimum EV percentage to include (default 0)
        
    Returns:
        List of EV opportunities sorted by EV percentage
    """
    ev_opportunities = []
    
    # Analyze main markets (game spreads)
    for event in events_data:
        # Home and away teams
        event_id = event.get("event_id")
        home_team = event.get("home_team")
        away_team = event.get("away_team")
        commence_time = event.get("commence_time")
        
        # Analyze spread bets
        for side, team in [("away", away_team), ("home", home_team)]:
            # Get spread lines for this team
            spread_data = event["spread_data"][side]
            best_line = spread_data["best_line"]
            
            if not best_line:
                continue
                
            # Parse the line value from format like "-1.5 (+110)"
            try:
                parts = best_line.split(" ")
                spread_point = parts[0]
                american_odds_str = parts[1].strip("()")
                
                # Extract just the odds values from each book
                book_lines = spread_data["book_lines"]
                odds_by_book = {}
                
                for book, line_str in book_lines.items():
                    if not line_str:
                        continue
                        
                    # Only include lines with matching spread point
                    if line_str.startswith(spread_point):
                        try:
                            book_odds_str = line_str.split(" ")[1].strip("()")
                            if book_odds_str.startswith("+"):
                                odds_by_book[book] = int(book_odds_str[1:])
                            else:
                                odds_by_book[book] = int(book_odds_str)
                        except (IndexError, ValueError):
                            continue
                
                # Calculate +EV
                ev_data = calculate_positive_ev(odds_by_book)
                if ev_data and ev_data["ev_percentage"] > min_ev_threshold:
                    ev_opportunities.append({
                        "event_id": event_id,
                        "commence_time": commence_time,
                        "home_team": home_team,
                        "away_team": away_team,
                        "market_type": "Spread",
                        "team": team,
                        "line": spread_point,
                        "best_book": ev_data["best_book"],
                        "best_odds": ev_data["best_odds"],
                        "all_odds": ev_data["all_odds"],
                        "implied_probabilities": ev_data["implied_probabilities"],
                        "individual_ev": ev_data["individual_ev"],
                        "fair_odds": ev_data["fair_odds"],
                        "avg_implied_probability": ev_data["avg_implied_probability"],
                        "avg_american_odds": ev_data["avg_american_odds"],
                        "ev_percentage": ev_data["ev_percentage"],
                        "odds_variance": ev_data["odds_variance"],
                        "markets": ev_data["markets"]
                    })
            except (IndexError, ValueError):
                continue
        
        # Now analyze player props for this event
        try:
            # Fetch player props data for this event
            props_data = get_props_data_formatted(event_id)
            
            # Loop through each prop type (points, assists, rebounds)
            for prop_type, players in props_data.items():
                # Loop through each player and their prop line
                for prop_key, prop_data in players.items():
                    player_name = prop_data.get('player')
                    line = prop_data.get('line')
                    books = prop_data.get('books', {})
                    
                    if not player_name or not line or not books:
                        continue
                    
                    # Analyze over odds
                    over_odds_by_book = {}
                    for book_name, book_data in books.items():
                        over_price = book_data.get('over_price')
                        if over_price:
                            over_odds_by_book[book_name] = over_price
                    
                    # Calculate EV for over
                    if len(over_odds_by_book) > 1:  # Need at least 2 books for comparison
                        over_ev_data = calculate_positive_ev(over_odds_by_book)
                        if over_ev_data and over_ev_data["ev_percentage"] > min_ev_threshold:
                            ev_opportunities.append({
                                "event_id": event_id,
                                "commence_time": commence_time,
                                "home_team": home_team,
                                "away_team": away_team,
                                "market_type": f"Player {prop_type.capitalize()}",
                                "team": player_name,
                                "line": f"Over {line}",
                                "best_book": over_ev_data["best_book"],
                                "best_odds": over_ev_data["best_odds"],
                                "all_odds": over_ev_data["all_odds"],
                                "implied_probabilities": over_ev_data["implied_probabilities"],
                                "individual_ev": over_ev_data["individual_ev"],
                                "fair_odds": over_ev_data["fair_odds"],
                                "avg_implied_probability": over_ev_data["avg_implied_probability"],
                                "avg_american_odds": over_ev_data["avg_american_odds"],
                                "ev_percentage": over_ev_data["ev_percentage"],
                                "odds_variance": over_ev_data["odds_variance"],
                                "markets": over_ev_data["markets"]
                            })
                    
                    # Analyze under odds
                    under_odds_by_book = {}
                    for book_name, book_data in books.items():
                        under_price = book_data.get('under_price')
                        if under_price:
                            under_odds_by_book[book_name] = under_price
                    
                    # Calculate EV for under
                    if len(under_odds_by_book) > 1:  # Need at least 2 books for comparison
                        under_ev_data = calculate_positive_ev(under_odds_by_book)
                        if under_ev_data and under_ev_data["ev_percentage"] > min_ev_threshold:
                            ev_opportunities.append({
                                "event_id": event_id,
                                "commence_time": commence_time,
                                "home_team": home_team,
                                "away_team": away_team,
                                "market_type": f"Player {prop_type.capitalize()}",
                                "team": player_name,
                                "line": f"Under {line}",
                                "best_book": under_ev_data["best_book"],
                                "best_odds": under_ev_data["best_odds"],
                                "all_odds": under_ev_data["all_odds"],
                                "implied_probabilities": under_ev_data["implied_probabilities"],
                                "individual_ev": under_ev_data["individual_ev"],
                                "fair_odds": under_ev_data["fair_odds"],
                                "avg_implied_probability": under_ev_data["avg_implied_probability"],
                                "avg_american_odds": under_ev_data["avg_american_odds"],
                                "ev_percentage": under_ev_data["ev_percentage"],
                                "odds_variance": under_ev_data["odds_variance"],
                                "markets": under_ev_data["markets"]
                            })
        except Exception as e:
            print(f"Error processing props for event {event_id}: {str(e)}")
            continue
    
    # Sort by EV percentage (highest first)
    ev_opportunities.sort(key=lambda x: x["ev_percentage"], reverse=True)
    return ev_opportunities

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
    (away_team) and (home_team).
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
                    # Find the "Over" outcome to get the line
                    over_outcome = next((o for o in outcomes if o.get('name') == 'Over'), None)
                    if over_outcome:
                        point = over_outcome.get('point')
                        
                        # Create a unique key combining player name and line
                        prop_key = f"{player_name}_{point}"
                        
                        if prop_key not in formatted_props[prop_type]:
                            formatted_props[prop_type][prop_key] = {
                                'player': player_name,
                                'line': point,
                                'books': {}
                            }
                        
                        # Store both over/under prices
                        under_outcome = next((o for o in outcomes if o.get('name') == 'Under'), None)
                        formatted_props[prop_type][prop_key]['books'][book_name] = {
                            'point': point,
                            'over_price': over_outcome.get('price'),
                            'under_price': under_outcome.get('price') if under_outcome else None
                        }
        
        # Sort the props data alphabetically by player name within each prop type
        for prop_type in formatted_props:
            formatted_props[prop_type] = dict(sorted(
                formatted_props[prop_type].items(),
                key=lambda item: item[1]['player'].lower()  # Sort by player name (case-insensitive)
            ))
            
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


@app.route('/ev', methods=['GET'])
def ev_page():
    """Display positive EV opportunities for both game spreads and player props."""
    # Get all events data
    events_data = process_events()
    
    # Get filter parameters
    market_filter = request.args.get('market', 'all')
    min_ev = float(request.args.get('min_ev', '1.0'))
    
    # Find EV opportunities with the specified threshold
    ev_opportunities = find_ev_opportunities(events_data, min_ev_threshold=min_ev)
    
    # Apply market filter if specified
    if market_filter != 'all':
        if market_filter == 'spreads':
            ev_opportunities = [ev for ev in ev_opportunities if ev.get('market_type') == 'Spread']
        elif market_filter == 'player_props':
            ev_opportunities = [ev for ev in ev_opportunities if 'Player' in ev.get('market_type', '')]
        elif market_filter == 'points':
            ev_opportunities = [ev for ev in ev_opportunities if ev.get('market_type') == 'Player Points']
        elif market_filter == 'assists':
            ev_opportunities = [ev for ev in ev_opportunities if ev.get('market_type') == 'Player Assists']
        elif market_filter == 'rebounds':
            ev_opportunities = [ev for ev in ev_opportunities if ev.get('market_type') == 'Player Rebounds']
    
    # Get the list of all books for display
    all_books = set()
    for ev in ev_opportunities:
        if ev.get("all_odds"):
            all_books.update(ev.get("all_odds").keys())
    all_books = sorted(list(all_books))
    
    # Get available market types for filtering
    market_types = set()
    for ev in find_ev_opportunities(events_data, 0):  # Get all possible markets without filtering
        market_types.add(ev.get('market_type'))
    market_types = sorted(list(market_types))
    
    return render_template("ev.html", 
                         opportunities=ev_opportunities,
                         all_books=all_books,
                         market_types=market_types,
                         active_tab="ev",
                         current_filter=market_filter,
                         min_ev=min_ev)
# For local development
if __name__ == "__main__":
    app.run(debug=True)

# The magic happens here - let the Vercel handler use our Flask app
app.debug = True