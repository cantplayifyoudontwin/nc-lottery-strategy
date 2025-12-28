"""
NC Lottery Million Dollar Strategy Monitor
==========================================

This script monitors all NC Lottery scratch-off games with $1M+ prizes
and generates a strategic analysis report for optimizing play.

Key Metrics:
- Million+ prize tier health (% remaining)
- Mid-tier health ($500-$10K) for loss minimization
- Overall game differential
- Game maturity/age
- Days since launch

Output: HTML report deployed to GitHub Pages

Run manually when planning a session.
"""

import requests
from bs4 import BeautifulSoup
import re
import time
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
import os
import sys
import json


def get_eastern_time():
    """Get current time in Eastern timezone"""
    utc_now = datetime.now(timezone.utc)
    eastern = utc_now - timedelta(hours=5)
    return eastern


@dataclass
class PrizeTier:
    """Represents a single prize tier"""
    value: float
    total: int
    remaining: int
    
    @property
    def percent_remaining(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.remaining / self.total) * 100
    
    @property
    def is_million_plus(self) -> bool:
        return self.value >= 1_000_000
    
    def is_break_even_tier(self, ticket_price: float) -> bool:
        """Break-even tier: 2x to 10x ticket price"""
        floor = ticket_price * 2
        ceiling = ticket_price * 10
        return floor <= self.value <= ceiling
    
    def is_small_win_tier(self) -> bool:
        """Small wins: $500 - $1,000"""
        return 500 <= self.value <= 1_000
    
    def is_medium_win_tier(self) -> bool:
        """Medium wins: $2,000 - $10,000"""
        return 2_000 <= self.value <= 10_000


@dataclass 
class GameData:
    """Data structure for a scratch-off game"""
    game_number: str
    game_name: str
    ticket_price: float
    url: str
    start_date: Optional[str] = None
    status: str = ""
    prize_tiers: List[PrizeTier] = field(default_factory=list)
    
    def get_top_prize(self) -> Optional[PrizeTier]:
        if not self.prize_tiers:
            return None
        return max(self.prize_tiers, key=lambda x: x.value)
    
    def get_bottom_prize(self) -> Optional[PrizeTier]:
        if not self.prize_tiers:
            return None
        return min(self.prize_tiers, key=lambda x: x.value)
    
    def get_million_plus_tiers(self) -> List[PrizeTier]:
        return [t for t in self.prize_tiers if t.is_million_plus]
    
    def get_break_even_tiers(self) -> List[PrizeTier]:
        """Get tiers in break-even range (2x to 10x ticket price)"""
        return [t for t in self.prize_tiers if t.is_break_even_tier(self.ticket_price)]
    
    def get_small_win_tiers(self) -> List[PrizeTier]:
        """Get tiers in $500-$1,000 range"""
        return [t for t in self.prize_tiers if t.is_small_win_tier()]
    
    def get_medium_win_tiers(self) -> List[PrizeTier]:
        """Get tiers in $2,000-$10,000 range"""
        return [t for t in self.prize_tiers if t.is_medium_win_tier()]
    
    def calculate_differential(self) -> float:
        """Overall differential: top prize % - bottom prize %"""
        top = self.get_top_prize()
        bottom = self.get_bottom_prize()
        if not top or not bottom:
            return 0.0
        return top.percent_remaining - bottom.percent_remaining
    
    def calculate_million_health(self) -> Tuple[int, int, float]:
        """Returns (remaining, total, percent) for $1M+ prizes"""
        million_tiers = self.get_million_plus_tiers()
        if not million_tiers:
            return 0, 0, 0.0
        total = sum(t.total for t in million_tiers)
        remaining = sum(t.remaining for t in million_tiers)
        pct = (remaining / total * 100) if total > 0 else 0.0
        return remaining, total, pct
    
    def calculate_loss_minimization_score(self) -> float:
        """
        Calculate weighted loss minimization score.
        
        Weights:
        - Break-even tier (2x-10x ticket price): 50%
        - Small wins ($500-$1K): 30%
        - Medium wins ($2K-$10K): 20%
        
        Returns score from 0-100.
        """
        # Break-even tier (50% weight)
        break_even = self.get_break_even_tiers()
        if break_even:
            be_total = sum(t.total for t in break_even)
            be_remaining = sum(t.remaining for t in break_even)
            be_pct = (be_remaining / be_total * 100) if be_total > 0 else 0
        else:
            be_pct = 0
        
        # Small wins tier (30% weight)
        small_wins = self.get_small_win_tiers()
        if small_wins:
            sw_total = sum(t.total for t in small_wins)
            sw_remaining = sum(t.remaining for t in small_wins)
            sw_pct = (sw_remaining / sw_total * 100) if sw_total > 0 else 0
        else:
            sw_pct = 0
        
        # Medium wins tier (20% weight)
        medium_wins = self.get_medium_win_tiers()
        if medium_wins:
            mw_total = sum(t.total for t in medium_wins)
            mw_remaining = sum(t.remaining for t in medium_wins)
            mw_pct = (mw_remaining / mw_total * 100) if mw_total > 0 else 0
        else:
            mw_pct = 0
        
        # Weighted score
        score = (be_pct * 0.50) + (sw_pct * 0.30) + (mw_pct * 0.20)
        return score
    
    def calculate_bottom_depletion(self) -> float:
        """Returns % of bottom tier remaining (game maturity indicator)"""
        bottom = self.get_bottom_prize()
        if not bottom:
            return 0.0
        return bottom.percent_remaining
    
    def has_million_plus(self) -> bool:
        return len(self.get_million_plus_tiers()) > 0
    
    def days_since_launch(self) -> Optional[int]:
        """Calculate days since game launched"""
        if not self.start_date:
            return None
        try:
            # Try different date formats
            for fmt in ['%b %d, %Y', '%m/%d/%Y', '%Y-%m-%d']:
                try:
                    launch = datetime.strptime(self.start_date, fmt)
                    return (datetime.now() - launch).days
                except ValueError:
                    continue
            return None
        except:
            return None


class NCLotteryAnalyzer:
    """Analyzes NC Lottery scratch-off games"""
    
    BASE_URL = "https://nclottery.com"
    PRIZES_URL = f"{BASE_URL}/scratch-off-prizes-remaining"
    GAMES_ENDING_URL = f"{BASE_URL}/scratch-off-games-ending"
    
    def __init__(self, delay_seconds: float = 0.5, verbose: bool = True):
        self.delay = delay_seconds
        self.verbose = verbose
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
        self.games_in_claims = set()
    
    def log(self, message: str):
        if self.verbose:
            print(message)
    
    def fetch_page(self, url: str) -> Optional[str]:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                return response.text
            except requests.RequestException as e:
                self.log(f"  Attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(self.delay * 2)
        return None
    
    def parse_prize_value(self, prize_str: str) -> float:
        cleaned = prize_str.replace('$', '').replace(',', '').strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    
    def parse_number(self, num_str: str) -> int:
        cleaned = num_str.replace(',', '').strip()
        try:
            return int(cleaned)
        except ValueError:
            return 0
    
    def get_games_in_claims_period(self) -> set:
        self.log("Checking for games in claims period...")
        html = self.fetch_page(self.GAMES_ENDING_URL)
        if not html:
            return set()
        
        soup = BeautifulSoup(html, 'html.parser')
        claims_games = set()
        today = datetime.now()
        
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all('td')
                if len(cells) >= 5:
                    try:
                        game_num = cells[0].get_text(strip=True)
                        end_date_str = cells[3].get_text(strip=True)
                        claim_date_str = cells[4].get_text(strip=True)
                        
                        try:
                            end_date = datetime.strptime(end_date_str, '%b %d, %Y')
                            claim_date = datetime.strptime(claim_date_str, '%b %d, %Y')
                            
                            if end_date < today <= claim_date:
                                claims_games.add(game_num)
                        except ValueError:
                            pass
                    except (IndexError, AttributeError):
                        continue
        
        return claims_games
    
    def get_game_details_from_page(self, game_url: str) -> Tuple[float, Optional[str]]:
        """Get ticket price and start date from game page"""
        time.sleep(self.delay)
        
        html = self.fetch_page(game_url)
        if not html:
            return 0.0, None
        
        soup = BeautifulSoup(html, 'html.parser')
        page_text = soup.get_text()
        
        # Get price
        price = 0.0
        price_match = re.search(r'Ticket\s*Price\s*\$(\d+)', page_text, re.IGNORECASE)
        if price_match:
            price = float(price_match.group(1))
        else:
            for element in soup.find_all(['div', 'span', 'p', 'td']):
                text = element.get_text(strip=True)
                if 'Ticket Price' in text:
                    price_match = re.search(r'\$(\d+)', text)
                    if price_match:
                        price = float(price_match.group(1))
                        break
        
        # Get start date
        start_date = None
        date_match = re.search(r'Start\s*Date[:\s]*([A-Za-z]+\s+\d+,?\s+\d{4})', page_text, re.IGNORECASE)
        if date_match:
            start_date = date_match.group(1)
        else:
            # Try another pattern
            date_match = re.search(r'Began[:\s]*([A-Za-z]+\s+\d+,?\s+\d{4})', page_text, re.IGNORECASE)
            if date_match:
                start_date = date_match.group(1)
        
        return price, start_date
    
    def parse_game_section(self, game_table) -> Optional[GameData]:
        try:
            rows = game_table.find_all('tr')
            if len(rows) < 2:
                return None
            
            header_row = rows[0]
            game_link = header_row.find('a', href=re.compile(r'/scratch-off/\d+/'))
            if not game_link:
                return None
            
            href = game_link['href']
            game_name = game_link.get_text(strip=True)
            
            game_num_match = re.search(r'/scratch-off/(\d+)/', href)
            if not game_num_match:
                return None
            game_number = game_num_match.group(1)
            
            header_text = header_row.get_text()
            num_in_text = re.search(r'Game\s*Number:\s*(\d+)', header_text)
            if num_in_text:
                game_number = num_in_text.group(1)
            
            status = "Reordered" if "Reordered" in header_text else ""
            game_url = self.BASE_URL + href
            
            prize_tiers = []
            for row in rows[1:]:
                cells = row.find_all('td')
                if len(cells) >= 4:
                    try:
                        value_text = cells[0].get_text(strip=True)
                        if not value_text.startswith('$'):
                            continue
                        
                        prize_value = self.parse_prize_value(value_text)
                        if prize_value <= 0:
                            continue
                        
                        total = self.parse_number(cells[2].get_text(strip=True))
                        remaining = self.parse_number(cells[3].get_text(strip=True))
                        
                        if total > 0:
                            prize_tiers.append(PrizeTier(
                                value=prize_value,
                                total=total,
                                remaining=remaining
                            ))
                    except (IndexError, ValueError):
                        continue
            
            if not prize_tiers:
                return None
            
            return GameData(
                game_number=game_number,
                game_name=game_name,
                ticket_price=0.0,
                url=game_url,
                status=status,
                prize_tiers=prize_tiers
            )
            
        except Exception as e:
            return None
    
    def scrape_all_games(self) -> List[GameData]:
        """Scrape all active games with full prize tier data"""
        self.games_in_claims = self.get_games_in_claims_period()
        
        self.log("\nFetching prizes remaining page...")
        html = self.fetch_page(self.PRIZES_URL)
        if not html:
            return []
        
        soup = BeautifulSoup(html, 'html.parser')
        games = []
        all_tables = soup.find_all('table')
        
        self.log(f"Found {len(all_tables)} tables to analyze...")
        
        processed_games = set()
        
        for table in all_tables:
            game_link = table.find('a', href=re.compile(r'/scratch-off/\d+/'))
            if not game_link:
                continue
            
            href = game_link['href']
            game_num_match = re.search(r'/scratch-off/(\d+)/', href)
            if not game_num_match:
                continue
            
            game_number = game_num_match.group(1)
            
            if game_number in processed_games:
                continue
            
            if game_number in self.games_in_claims:
                self.log(f"Skipping Game #{game_number} - in claims period")
                processed_games.add(game_number)
                continue
            
            game_data = self.parse_game_section(table)
            
            if game_data:
                processed_games.add(game_number)
                self.log(f"Processing Game #{game_data.game_number}: {game_data.game_name}")
                
                price, start_date = self.get_game_details_from_page(game_data.url)
                game_data.ticket_price = price
                game_data.start_date = start_date
                
                if game_data.ticket_price > 0:
                    has_million = "[$1M+]" if game_data.has_million_plus() else ""
                    self.log(f"  Price: ${game_data.ticket_price:.0f}, Tiers: {len(game_data.prize_tiers)} {has_million}")
                    games.append(game_data)
        
        return games
    
    def get_million_plus_games(self) -> List[GameData]:
        """Get only games with $1M+ prizes"""
        all_games = self.scrape_all_games()
        million_games = [g for g in all_games if g.has_million_plus()]
        self.log(f"\nFound {len(million_games)} games with $1M+ prizes")
        return million_games


def format_currency(value: float) -> str:
    """Format currency for display"""
    if value >= 1_000_000:
        return f"${value/1_000_000:.1f}M"
    elif value >= 1_000:
        return f"${value/1_000:.0f}K"
    else:
        return f"${value:.0f}"


def calculate_composite_score(game: GameData) -> float:
    """
    Calculate a composite score for ranking games.
    Higher = better opportunity.
    
    Weights:
    - Million health: 40% (primary goal)
    - Loss minimization: 30% (weighted tier analysis)
    - Overall differential: 20% (game value)
    - Freshness bonus: 10% (newer games)
    """
    _, _, million_pct = game.calculate_million_health()
    loss_min_score = game.calculate_loss_minimization_score()
    diff = game.calculate_differential()
    
    # Normalize differential to 0-100 scale (typically ranges from -30 to +30)
    diff_normalized = max(0, min(100, (diff + 30) * (100/60)))
    
    # Freshness: newer games get a bonus
    days = game.days_since_launch()
    if days is not None:
        if days < 30:
            freshness = 100
        elif days < 90:
            freshness = 75
        elif days < 180:
            freshness = 50
        else:
            freshness = 25
    else:
        freshness = 50  # Unknown age, neutral score
    
    score = (
        million_pct * 0.40 +
        loss_min_score * 0.30 +
        diff_normalized * 0.20 +
        freshness * 0.10
    )
    
    return score


def categorize_game(game: GameData) -> str:
    """Categorize game as HOT, WATCH, or AVOID"""
    _, _, million_pct = game.calculate_million_health()
    bottom_pct = game.calculate_bottom_depletion()
    diff = game.calculate_differential()
    
    # HOT: Strong million retention with good differential
    if million_pct >= 70 and diff > 0:
        return "HOT"
    
    # Also HOT: Million prizes healthier than game maturity suggests
    if million_pct > bottom_pct + 10:
        return "HOT"
    
    # AVOID: Million prizes heavily depleted
    if million_pct < 30:
        return "AVOID"
    
    # AVOID: Million depleting faster than game
    if million_pct < bottom_pct - 15:
        return "AVOID"
    
    # Everything else is WATCH
    return "WATCH"


def generate_html_report(games: List[GameData]) -> str:
    """Generate the HTML strategy report"""
    
    eastern_now = get_eastern_time()
    report_time = eastern_now.strftime('%B %d, %Y at %I:%M %p') + ' EST'
    
    # Sort games by composite score
    scored_games = [(g, calculate_composite_score(g), categorize_game(g)) for g in games]
    scored_games.sort(key=lambda x: x[1], reverse=True)
    
    # Separate by category
    hot_games = [(g, s) for g, s, c in scored_games if c == "HOT"]
    watch_games = [(g, s) for g, s, c in scored_games if c == "WATCH"]
    avoid_games = [(g, s) for g, s, c in scored_games if c == "AVOID"]
    
    def generate_game_card(game: GameData, score: float, rank: int = None) -> str:
        """Generate HTML for a single game card"""
        million_rem, million_tot, million_pct = game.calculate_million_health()
        loss_min_score = game.calculate_loss_minimization_score()
        bottom_pct = game.calculate_bottom_depletion()
        diff = game.calculate_differential()
        days = game.days_since_launch()
        
        # Color coding
        million_color = "#00FF88" if million_pct >= 70 else "#FFD700" if million_pct >= 40 else "#FF6B6B"
        loss_min_color = "#00FF88" if loss_min_score >= 70 else "#FFD700" if loss_min_score >= 50 else "#FF6B6B"
        diff_color = "#00FF88" if diff > 0 else "#FF6B6B"
        
        # Days display
        days_str = f"{days} days old" if days else "Age unknown"
        days_badge = ""
        if days is not None:
            if days < 30:
                days_badge = '<span class="badge new">NEW</span>'
            elif days < 90:
                days_badge = '<span class="badge fresh">FRESH</span>'
        
        # Million tier breakdown
        million_tiers = game.get_million_plus_tiers()
        million_breakdown = ""
        for tier in sorted(million_tiers, key=lambda x: x.value, reverse=True):
            tier_color = "#00FF88" if tier.percent_remaining >= 70 else "#FFD700" if tier.percent_remaining >= 40 else "#FF6B6B"
            million_breakdown += f'''
                <div class="tier-row">
                    <span class="tier-value">{format_currency(tier.value)}</span>
                    <span class="tier-remaining" style="color: {tier_color}">{tier.remaining} of {tier.total} ({tier.percent_remaining:.0f}%)</span>
                </div>
            '''
        
        rank_display = f'<span class="rank">#{rank}</span>' if rank else ''
        
        return f'''
        <div class="game-card">
            <div class="game-header">
                {rank_display}
                <div class="game-title">
                    <h3>{game.game_name} {days_badge}</h3>
                    <span class="game-meta">${int(game.ticket_price)} ticket • Game #{game.game_number} • {days_str}</span>
                </div>
                <div class="score">Score: {score:.0f}</div>
            </div>
            
            <div class="metrics-grid">
                <div class="metric">
                    <div class="metric-label">MILLION+ PRIZES</div>
                    <div class="metric-value" style="color: {million_color}">{million_rem} of {million_tot} ({million_pct:.0f}%)</div>
                    <div class="tier-breakdown">
                        {million_breakdown}
                    </div>
                </div>
                
                <div class="metric">
                    <div class="metric-label">LOSS MINIMIZATION</div>
                    <div class="metric-value" style="color: {loss_min_color}">{loss_min_score:.0f}</div>
                    <div class="metric-sub">Weighted score (0-100)</div>
                </div>
                
                <div class="metric">
                    <div class="metric-label">GAME MATURITY</div>
                    <div class="metric-value">{100 - bottom_pct:.0f}% sold</div>
                    <div class="metric-sub">Based on bottom prize depletion</div>
                </div>
                
                <div class="metric">
                    <div class="metric-label">DIFFERENTIAL</div>
                    <div class="metric-value" style="color: {diff_color}">{diff:+.1f}%</div>
                    <div class="metric-sub">Top vs bottom prize %</div>
                </div>
            </div>
            
            <a href="{game.url}" target="_blank" class="game-link">View on NC Lottery →</a>
        </div>
        '''
    
    # Generate quick reference table
    quick_ref_rows = ""
    for rank, (game, score, cat) in enumerate(scored_games, 1):
        million_rem, million_tot, million_pct = game.calculate_million_health()
        loss_min_score = game.calculate_loss_minimization_score()
        diff = game.calculate_differential()
        
        cat_class = cat.lower()
        diff_color = "#00FF88" if diff > 0 else "#FF6B6B"
        loss_min_color = "#00FF88" if loss_min_score >= 70 else "#FFD700" if loss_min_score >= 50 else "#FF6B6B"
        
        quick_ref_rows += f'''
            <tr class="cat-{cat_class}">
                <td>{rank}</td>
                <td class="game-name-cell">{game.game_name}</td>
                <td>${int(game.ticket_price)}</td>
                <td>{million_rem}/{million_tot} ({million_pct:.0f}%)</td>
                <td style="color: {loss_min_color}">{loss_min_score:.0f}</td>
                <td style="color: {diff_color}">{diff:+.1f}%</td>
                <td><span class="cat-badge {cat_class}">{cat}</span></td>
                <td>{score:.0f}</td>
            </tr>
        '''
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NC Lottery $1M+ Strategy Monitor</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-primary: #0a0a0f;
            --bg-secondary: #14141c;
            --bg-card: #1c1c28;
            --text-primary: #ffffff;
            --text-secondary: #b8b8c8;
            --text-muted: #7a7a90;
            --accent-green: #00FF88;
            --accent-gold: #FFD700;
            --accent-red: #FF6B6B;
            --accent-cyan: #00FFFF;
            --border-color: rgba(255,255,255,0.12);
        }}
        
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'Outfit', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            padding: 2rem;
            font-weight: 400;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        header {{
            text-align: center;
            padding: 2rem 0 3rem;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 2rem;
        }}
        
        h1 {{
            font-size: 2.5rem;
            font-weight: 800;
            color: var(--accent-gold);
            margin-bottom: 0.5rem;
        }}
        
        .subtitle {{
            color: var(--text-secondary);
            font-size: 1.1rem;
        }}
        
        .report-time {{
            display: inline-block;
            margin-top: 1rem;
            padding: 0.5rem 1rem;
            background: var(--bg-secondary);
            border-radius: 2rem;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.85rem;
            color: var(--text-muted);
        }}
        
        .section {{
            margin-bottom: 3rem;
        }}
        
        .section-header {{
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-bottom: 1.5rem;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid var(--border-color);
        }}
        
        .section-icon {{
            font-size: 1.5rem;
        }}
        
        .section-title {{
            font-size: 1.5rem;
            font-weight: 700;
        }}
        
        .section-count {{
            background: var(--bg-card);
            padding: 0.25rem 0.75rem;
            border-radius: 1rem;
            font-size: 0.85rem;
            color: var(--text-secondary);
        }}
        
        .hot .section-title {{ color: var(--accent-green); }}
        .watch .section-title {{ color: var(--accent-gold); }}
        .avoid .section-title {{ color: var(--accent-red); }}
        
        .game-card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 1rem;
            padding: 1.5rem;
            margin-bottom: 1rem;
        }}
        
        .game-header {{
            display: flex;
            align-items: flex-start;
            gap: 1rem;
            margin-bottom: 1.5rem;
        }}
        
        .rank {{
            background: linear-gradient(135deg, #4A90D9, #8B5CF6);
            color: white;
            font-weight: 700;
            font-size: 1.25rem;
            padding: 0.5rem 1rem;
            border-radius: 0.5rem;
            font-family: 'JetBrains Mono', monospace;
        }}
        
        .game-title {{
            flex: 1;
        }}
        
        .game-title h3 {{
            font-size: 1.25rem;
            font-weight: 600;
            margin-bottom: 0.25rem;
        }}
        
        .game-meta {{
            font-size: 0.9rem;
            color: var(--text-secondary);
            font-weight: 500;
        }}
        
        .score {{
            background: var(--bg-secondary);
            padding: 0.5rem 1rem;
            border-radius: 0.5rem;
            font-family: 'JetBrains Mono', monospace;
            font-weight: 700;
            font-size: 1.1rem;
            color: var(--accent-cyan);
        }}
        
        .badge {{
            display: inline-block;
            padding: 0.15rem 0.5rem;
            border-radius: 0.25rem;
            font-size: 0.7rem;
            font-weight: 600;
            margin-left: 0.5rem;
            text-transform: uppercase;
        }}
        
        .badge.new {{
            background: var(--accent-green);
            color: black;
        }}
        
        .badge.fresh {{
            background: var(--accent-cyan);
            color: black;
        }}
        
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 1rem;
        }}
        
        .metric {{
            background: var(--bg-secondary);
            padding: 1rem;
            border-radius: 0.5rem;
        }}
        
        .metric-label {{
            font-size: 0.8rem;
            font-weight: 700;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.5rem;
        }}
        
        .metric-value {{
            font-size: 1.4rem;
            font-weight: 700;
            font-family: 'JetBrains Mono', monospace;
        }}
        
        .metric-sub {{
            font-size: 0.85rem;
            color: var(--text-muted);
            margin-top: 0.25rem;
            font-weight: 500;
        }}
        
        .tier-breakdown {{
            margin-top: 0.75rem;
            padding-top: 0.75rem;
            border-top: 1px solid var(--border-color);
        }}
        
        .tier-row {{
            display: flex;
            justify-content: space-between;
            font-size: 0.9rem;
            padding: 0.35rem 0;
        }}
        
        .tier-value {{
            color: var(--text-secondary);
            font-weight: 500;
        }}
        
        .tier-remaining {{
            font-family: 'JetBrains Mono', monospace;
            font-weight: 600;
        }}
        
        .game-link {{
            display: inline-block;
            color: var(--accent-cyan);
            text-decoration: none;
            font-size: 0.9rem;
        }}
        
        .game-link:hover {{
            text-decoration: underline;
        }}
        
        /* Quick Reference Table */
        .quick-ref {{
            background: var(--bg-card);
            border-radius: 1rem;
            overflow: hidden;
            margin-top: 2rem;
        }}
        
        .quick-ref table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
        .quick-ref th {{
            background: var(--bg-secondary);
            padding: 1rem;
            text-align: left;
            font-size: 0.8rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--accent-cyan);
        }}
        
        .quick-ref td {{
            padding: 0.85rem 1rem;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.95rem;
            font-weight: 500;
        }}
        
        .quick-ref tr:last-child td {{
            border-bottom: none;
        }}
        
        .quick-ref .game-name-cell {{
            font-weight: 500;
        }}
        
        .cat-badge {{
            display: inline-block;
            padding: 0.2rem 0.5rem;
            border-radius: 0.25rem;
            font-size: 0.7rem;
            font-weight: 600;
        }}
        
        .cat-badge.hot {{
            background: rgba(0, 255, 136, 0.2);
            color: var(--accent-green);
        }}
        
        .cat-badge.watch {{
            background: rgba(255, 215, 0, 0.2);
            color: var(--accent-gold);
        }}
        
        .cat-badge.avoid {{
            background: rgba(255, 107, 107, 0.2);
            color: var(--accent-red);
        }}
        
        .cat-hot {{ background: rgba(0, 255, 136, 0.05); }}
        .cat-avoid {{ background: rgba(255, 107, 107, 0.05); }}
        
        /* Info Box */
        .info-box {{
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-left: 4px solid var(--accent-cyan);
            border-radius: 0.5rem;
            padding: 1.5rem;
            margin-bottom: 2rem;
        }}
        
        .info-box h3 {{
            color: var(--accent-cyan);
            margin-bottom: 0.75rem;
            font-size: 1.1rem;
        }}
        
        .info-box p {{
            color: var(--text-secondary);
            font-size: 1rem;
            margin-bottom: 0.5rem;
            font-weight: 400;
        }}
        
        /* Responsive */
        @media (max-width: 768px) {{
            body {{ padding: 1rem; }}
            h1 {{ font-size: 1.75rem; }}
            .game-header {{ flex-direction: column; }}
            .metrics-grid {{ grid-template-columns: 1fr; }}
            .quick-ref {{ overflow-x: auto; }}
            .quick-ref table {{ min-width: 700px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>💰 NC Lottery $1M+ Strategy Monitor</h1>
            <p class="subtitle">Strategic analysis for million-dollar prize hunting</p>
            <div class="report-time">Generated: {report_time}</div>
        </header>
        
        <div class="info-box">
            <h3>📊 How to Use This Report</h3>
            <p><strong>Score</strong> combines: Million prize health (40%), Loss minimization (30%), Overall differential (20%), and Game freshness (10%).</p>
            <p><strong>Loss Minimization</strong> is a weighted score (0-100) based on: break-even prizes at 50%, small wins $500-$1K at 30%, medium wins $2K-$10K at 20%.</p>
            <p><strong>🔥 HOT:</strong> Strong million retention + positive indicators. Best opportunities.</p>
            <p><strong>⚠️ WATCH:</strong> Decent potential but some concerns. Consider carefully.</p>
            <p><strong>📉 AVOID:</strong> Million prizes depleted or depleting faster than expected.</p>
            <p style="margin-top: 1rem; font-style: italic;">This is analysis, not advice. All lottery play involves risk. Play responsibly.</p>
        </div>
        
        <div class="section hot">
            <div class="section-header">
                <span class="section-icon">🔥</span>
                <h2 class="section-title">Top Opportunities</h2>
                <span class="section-count">{len(hot_games)} games</span>
            </div>
            {''.join(generate_game_card(g, s, i+1) for i, (g, s) in enumerate(hot_games)) if hot_games else '<p style="color: var(--text-muted);">No games currently meet HOT criteria.</p>'}
        </div>
        
        <div class="section watch">
            <div class="section-header">
                <span class="section-icon">⚠️</span>
                <h2 class="section-title">Watch List</h2>
                <span class="section-count">{len(watch_games)} games</span>
            </div>
            {''.join(generate_game_card(g, s) for g, s in watch_games) if watch_games else '<p style="color: var(--text-muted);">No games currently on watch list.</p>'}
        </div>
        
        <div class="section avoid">
            <div class="section-header">
                <span class="section-icon">📉</span>
                <h2 class="section-title">Avoid for $1M Strategy</h2>
                <span class="section-count">{len(avoid_games)} games</span>
            </div>
            {''.join(generate_game_card(g, s) for g, s in avoid_games) if avoid_games else '<p style="color: var(--text-muted);">No games currently in avoid category.</p>'}
        </div>
        
        <div class="section">
            <div class="section-header">
                <span class="section-icon">📋</span>
                <h2 class="section-title" style="color: var(--text-primary);">Quick Reference: All $1M+ Games</h2>
            </div>
            <div class="quick-ref">
                <table>
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Game</th>
                            <th>Price</th>
                            <th>$1M+ Left</th>
                            <th>Loss Min</th>
                            <th>Diff</th>
                            <th>Status</th>
                            <th>Score</th>
                        </tr>
                    </thead>
                    <tbody>
                        {quick_ref_rows}
                    </tbody>
                </table>
            </div>
        </div>
        
        <footer style="text-align: center; padding: 2rem 0; color: var(--text-muted); font-size: 0.85rem;">
            <p>Data sourced from <a href="https://nclottery.com" target="_blank" style="color: var(--accent-cyan);">NC Education Lottery</a></p>
            <p>This tool is for informational purposes only. Lottery games are games of chance. Play responsibly.</p>
        </footer>
    </div>
</body>
</html>
'''
    
    return html


def main():
    """Main execution function"""
    print("=" * 60)
    print("NC Lottery $1M+ Strategy Monitor")
    print("=" * 60)
    
    eastern_now = get_eastern_time()
    print(f"Started at: {eastern_now.strftime('%Y-%m-%d %H:%M:%S')} Eastern")
    print()
    
    # Run analysis
    analyzer = NCLotteryAnalyzer(delay_seconds=0.5, verbose=True)
    million_games = analyzer.get_million_plus_games()
    
    if not million_games:
        print("\nERROR: No games with $1M+ prizes found!")
        sys.exit(1)
    
    print(f"\n{'=' * 60}")
    print(f"ANALYSIS COMPLETE: {len(million_games)} games with $1M+ prizes")
    print("=" * 60)
    
    # Show quick summary
    scored = [(g, calculate_composite_score(g), categorize_game(g)) for g in million_games]
    scored.sort(key=lambda x: x[1], reverse=True)
    
    print("\nTop 5 Opportunities:")
    for i, (game, score, cat) in enumerate(scored[:5], 1):
        million_rem, million_tot, million_pct = game.calculate_million_health()
        print(f"  #{i}: {game.game_name} (${int(game.ticket_price)})")
        print(f"      $1M+: {million_rem}/{million_tot} ({million_pct:.0f}%) | Score: {score:.0f} | {cat}")
    
    # Generate HTML report
    print("\nGenerating HTML report...")
    html = generate_html_report(million_games)
    
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"Report saved to: index.html")
    print(f"\nFinished at: {get_eastern_time().strftime('%Y-%m-%d %H:%M:%S')} Eastern")


if __name__ == "__main__":
    main()
