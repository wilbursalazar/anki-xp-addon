import os
import json
import datetime
import random
from aqt import mw
from aqt.qt import *
from aqt.utils import showInfo, tooltip
from anki.hooks import addHook, wrap
from aqt.reviewer import Reviewer

# Print debug info
print("XP Add-on: Starting initialization...")

# Configuration
BASE_XP_AGAIN = -5
BASE_XP_HARD = -2
BASE_XP_GOOD = 5
BASE_XP_EASY = 10
MULTIPLIER_INCREMENT = 0.2
MULTIPLIER_DECAY = 0.5
MAX_MULTIPLIER = 5.0

# Level configuration
BASE_XP_FOR_LEVEL = 100
LEVEL_FACTOR = 1.5
MAX_LEVEL = 100

# Skill points configuration
SKILL_POINTS_PER_LEVEL = 1

# Define skill tree
SKILL_TREE = {
    "xp_boost": {
        "name": "XP Boost",
        "description": "Increases base XP earned by 10% per level",
        "max_level": 5,
        "effect_per_level": 0.1,  # 10% boost per level
        "cost": 1,  # Skill points cost per level
        "prerequisite": None,
        "icon": "⬆️"
    },
    "multiplier_boost": {
        "name": "Multiplier Boost",
        "description": "Increases the multiplier increment by 0.05 per level",
        "max_level": 3,
        "effect_per_level": 0.05,
        "cost": 1,
        "prerequisite": "xp_boost:1",  # Requires XP Boost level 1
        "icon": "✖️"
    },
    "streak_shield": {
        "name": "Streak Shield",
        "description": "Reduces streak loss on Hard answers by 20% per level",
        "max_level": 3,
        "effect_per_level": 0.2,  # 20% chance per level to not lose streak on Hard
        "cost": 1,
        "prerequisite": None,
        "icon": "🛡️"
    },
    "recovery": {
        "name": "Quick Recovery",
        "description": "Reduces multiplier decay by 0.1 per level",
        "max_level": 2,
        "effect_per_level": 0.1,
        "cost": 1,
        "prerequisite": "streak_shield:2",  # Requires Streak Shield level 2
        "icon": "🔄"
    },
    "daily_bonus": {
        "name": "Daily Bonus",
        "description": "Earn 25 bonus XP at the start of each day per level",
        "max_level": 4,
        "effect_per_level": 25,
        "cost": 1,
        "prerequisite": "xp_boost:2",  # Requires XP Boost level 2
        "icon": "🎁"
    }
}

# Define achievements
ACHIEVEMENTS = {
    "novice": {
        "name": "Novice Learner",
        "description": "Reach level 5",
        "requirement": "level >= 5",
        "reward_xp": 100,
        "icon": "🎓",
        "hidden": False
    },
    "intermediate": {
        "name": "Intermediate Scholar",
        "description": "Reach level 10",
        "reward_xp": 250,
        "requirement": "level >= 10",
        "icon": "📚",
        "hidden": False
    },
    "advanced": {
        "name": "Advanced Academic",
        "description": "Reach level 25",
        "reward_xp": 500,
        "requirement": "level >= 25",
        "icon": "🧠",
        "hidden": False
    },
    "combo_master": {
        "name": "Combo Master",
        "description": "Reach a 10-card streak",
        "reward_xp": 50,
        "requirement": "streak >= 10",
        "icon": "🔥",
        "hidden": False
    },
    "multiplier_king": {
        "name": "Multiplier King",
        "description": "Reach maximum multiplier (5x)",
        "reward_xp": 100,
        "requirement": "multiplier >= 5.0",
        "icon": "👑",
        "hidden": False
    },
    "skill_starter": {
        "name": "Skill Starter",
        "description": "Unlock your first skill",
        "reward_xp": 50,
        "requirement": "total_skills_unlocked >= 1",
        "icon": "🌱",
        "hidden": False
    },
    "persistent": {
        "name": "Persistent Student",
        "description": "Study for 7 consecutive days",
        "reward_xp": 150,
        "requirement": "study_streak >= 7",
        "icon": "📅",
        "hidden": False
    }
}

# Global data
xp_state = {
    "daily_xp": 0,
    "total_xp": 0,
    "multiplier": 1.0,
    "streak": 0,
    "high_score": 0,
    "date": "",
    "level": 1,
    "skill_points": 0,
    "skills": {},  # Format: {"skill_id": level}
    "achievements": {},  # Format: {"achievement_id": {"earned": True, "date": "YYYY-MM-DD"}}
    "xp_history": {},  # Format: {"YYYY-MM-DD": xp_earned_that_day}
    "study_streak": 0,  # Consecutive days studied
    "last_study_date": ""
}

# Get file path
def get_file_path():
    addon_dir = os.path.dirname(os.path.realpath(__file__))
    return os.path.join(addon_dir, "xp_data.json")

# Save state
def save_state():
    try:
        with open(get_file_path(), "w") as f:
            json.dump(xp_state, f)
    except Exception as e:
        print(f"Error saving state: {str(e)}")

# Calculate level from XP
def calculate_level(xp):
    level = 1
    xp_required = BASE_XP_FOR_LEVEL
    xp_for_next_level = xp_required
    
    while xp >= xp_for_next_level and level < MAX_LEVEL:
        level += 1
        xp_required = int(BASE_XP_FOR_LEVEL * (LEVEL_FACTOR ** (level - 1)))
        xp_for_next_level += xp_required
    
    # Calculate progress to next level (as percentage)
    if level < MAX_LEVEL:
        next_level_xp = int(BASE_XP_FOR_LEVEL * (LEVEL_FACTOR ** level))
        current_level_total = xp_for_next_level - next_level_xp
        progress = ((xp - current_level_total) / next_level_xp) * 100
        progress = min(100, max(0, progress))  # Ensure between 0-100
    else:
        progress = 100
        
    return level, int(progress), xp_for_next_level - xp

# Apply skill effects
def apply_skill_effects(effect_type, base_value):
    if effect_type == "xp_boost":
        # Apply XP boost skill
        skill_level = xp_state["skills"].get("xp_boost", 0)
        if skill_level > 0:
            boost = 1 + (skill_level * SKILL_TREE["xp_boost"]["effect_per_level"])
            return base_value * boost
    elif effect_type == "multiplier_increment":
        # Apply multiplier boost skill
        skill_level = xp_state["skills"].get("multiplier_boost", 0)
        if skill_level > 0:
            boost = SKILL_TREE["multiplier_boost"]["effect_per_level"] * skill_level
            return base_value + boost
    elif effect_type == "streak_shield":
        # Apply streak shield skill (chance to not lose streak on Hard)
        skill_level = xp_state["skills"].get("streak_shield", 0)
        if skill_level > 0:
            chance = SKILL_TREE["streak_shield"]["effect_per_level"] * skill_level
            return random.random() < chance  # True if shield activates
    elif effect_type == "multiplier_decay":
        # Apply recovery skill (reduce multiplier decay)
        skill_level = xp_state["skills"].get("recovery", 0)
        if skill_level > 0:
            reduction = SKILL_TREE["recovery"]["effect_per_level"] * skill_level
            return max(0, base_value - reduction)
    
    # Default if no skill applies or skill level is 0
    return base_value

# Check if any achievements have been earned
def check_achievements():
    new_achievements = []
    
    for ach_id, achievement in ACHIEVEMENTS.items():
        # Skip if already earned
        if ach_id in xp_state["achievements"] and xp_state["achievements"][ach_id]["earned"]:
            continue
            
        # Check requirement
        requirement = achievement["requirement"]
        earned = False
        
        # Evaluate the requirement
        if "level >= " in requirement:
            level_req = int(requirement.split(">=")[1].strip())
            earned = xp_state["level"] >= level_req
        elif "daily_xp >= " in requirement:
            xp_req = int(requirement.split(">=")[1].strip())
            earned = xp_state["daily_xp"] >= xp_req
        elif "streak >= " in requirement:
            streak_req = int(requirement.split(">=")[1].strip())
            earned = xp_state["streak"] >= streak_req
        elif "multiplier >= " in requirement:
            multi_req = float(requirement.split(">=")[1].strip())
            earned = xp_state["multiplier"] >= multi_req
        elif "total_skills_unlocked >= " in requirement:
            skills_req = int(requirement.split(">=")[1].strip())
            total_skills = sum(1 for skill_level in xp_state["skills"].values() if skill_level > 0)
            earned = total_skills >= skills_req
        elif "has_maxed_skill == True" in requirement:
            earned = any(xp_state["skills"].get(skill_id, 0) >= skill["max_level"] 
                        for skill_id, skill in SKILL_TREE.items())
        elif "study_streak >= " in requirement:
            streak_req = int(requirement.split(">=")[1].strip())
            earned = xp_state["study_streak"] >= streak_req
            
        # If earned, add to the list
        if earned:
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            xp_state["achievements"][ach_id] = {
                "earned": True,
                "date": today
            }
            new_achievements.append(achievement)
            
            # Award XP bonus
            xp_state["total_xp"] += achievement["reward_xp"]
            
    return new_achievements

# Apply daily bonus from skills
def apply_daily_bonus():
    daily_bonus_level = xp_state["skills"].get("daily_bonus", 0)
    if daily_bonus_level > 0:
        bonus_xp = daily_bonus_level * SKILL_TREE["daily_bonus"]["effect_per_level"]
        xp_state["daily_xp"] += bonus_xp
        xp_state["total_xp"] += bonus_xp
        return bonus_xp
    return 0

# Load state
def load_state():
    global xp_state
    try:
        if os.path.exists(get_file_path()):
            with open(get_file_path(), "r") as f:
                loaded_state = json.load(f)
                
                # Update with new fields if they don't exist (for backward compatibility)
                for key, value in xp_state.items():
                    if key not in loaded_state:
                        loaded_state[key] = value
                
                xp_state = loaded_state
        
        # Check for date change
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        
        # Update study streak
        if xp_state["last_study_date"] == yesterday:
            xp_state["study_streak"] += 1
        elif xp_state["last_study_date"] != today:
            # Reset streak if we missed a day
            xp_state["study_streak"] = 1
        
        if xp_state.get("date", "") != today:
            # Save high score
            if xp_state["daily_xp"] > xp_state["high_score"]:
                xp_state["high_score"] = xp_state["daily_xp"]
            
            # Save yesterday's XP to history
            if xp_state["date"] and xp_state["daily_xp"] > 0:
                xp_state["xp_history"][xp_state["date"]] = xp_state["daily_xp"]
            
            # Reset daily values
            xp_state["daily_xp"] = 0
            xp_state["multiplier"] = 1.0
            xp_state["streak"] = 0
            xp_state["date"] = today
            xp_state["last_study_date"] = today
            
            # Apply daily bonus if skill is unlocked
            bonus_xp = apply_daily_bonus()
            if bonus_xp > 0:
                tooltip(f"<div style='color: #00AA00; font-weight: bold;'>Daily Bonus: +{bonus_xp} XP</div>", period=2000)
            
            save_state()
            
        # Ensure level is updated based on total XP
        level, progress, xp_needed = calculate_level(xp_state["total_xp"])
        old_level = xp_state.get("level", 1)
        xp_state["level"] = level
        
        # Award skill points for new levels gained
        if level > old_level:
            points_to_add = (level - old_level) * SKILL_POINTS_PER_LEVEL
            xp_state["skill_points"] += points_to_add
            
        # Check achievements
        new_achievements = check_achievements()
        for achievement in new_achievements:
            tooltip(f"<div style='color: #FFD700; font-weight: bold;'>Achievement Unlocked: {achievement['icon']} {achievement['name']}</div><div>+{achievement['reward_xp']} XP</div>", period=3000)
            
    except Exception as e:
        # Reset to defaults if there's any problem
        print(f"Error loading state: {str(e)}")
        xp_state = {
            "daily_xp": 0,
            "total_xp": 0,
            "multiplier": 1.0,
            "streak": 0,
            "high_score": 0,
            "date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "level": 1,
            "skill_points": 0,
            "skills": {},
            "achievements": {},
            "xp_history": {},
            "study_streak": 1,
            "last_study_date": datetime.datetime.now().strftime("%Y-%m-%d")
        }
        save_state()

# Reset state
def reset_state():
    global xp_state
    xp_state = {
        "daily_xp": 0,
        "total_xp": 0,
        "multiplier": 1.0,
        "streak": 0,
        "high_score": 0,
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "level": 1,
        "skill_points": 0,
        "skills": {},
        "achievements": {},
        "xp_history": {},
        "study_streak": 1,
        "last_study_date": datetime.datetime.now().strftime("%Y-%m-%d")
    }
    save_state()
    update_display()
    showInfo("XP data has been reset.")

# XP calculation
def calculate_xp(ease):
    global xp_state
    
    # Base XP based on answer
    base_xp = 0
    if ease == 1:  # Again
        base_xp = BASE_XP_AGAIN
        xp_state["streak"] = 0
        xp_state["multiplier"] = max(1.0, xp_state["multiplier"] - MULTIPLIER_DECAY)
    elif ease == 2:  # Hard
        base_xp = BASE_XP_HARD
        # Check if streak shield activates
        if not apply_skill_effects("streak_shield", False):
            xp_state["streak"] = 0
        # Apply reduced multiplier decay if recovery skill is active
        decay = apply_skill_effects("multiplier_decay", MULTIPLIER_DECAY)
        xp_state["multiplier"] = max(1.0, xp_state["multiplier"] - decay)
    elif ease == 3:  # Good
        base_xp = BASE_XP_GOOD
        xp_state["streak"] += 1
        # Apply multiplier boost skill if available
        increment = apply_skill_effects("multiplier_increment", MULTIPLIER_INCREMENT)
        xp_state["multiplier"] = min(MAX_MULTIPLIER, xp_state["multiplier"] + increment)
    elif ease == 4:  # Easy
        base_xp = BASE_XP_EASY
        xp_state["streak"] += 1
        # Apply multiplier boost skill if available (doubled for Easy answers)
        increment = apply_skill_effects("multiplier_increment", MULTIPLIER_INCREMENT * 2)
        xp_state["multiplier"] = min(MAX_MULTIPLIER, xp_state["multiplier"] + increment)
    
    # Apply multiplier to positive XP
    if base_xp > 0:
        # Apply XP boost skill if available
        boosted_xp = apply_skill_effects("xp_boost", base_xp)
        earned_xp = int(boosted_xp * xp_state["multiplier"])
    else:
        earned_xp = base_xp
    
    # Update XP totals
    xp_state["daily_xp"] += earned_xp
    xp_state["total_xp"] += earned_xp
    
    # Update level based on total XP
    old_level = xp_state["level"]
    new_level, progress, xp_needed = calculate_level(xp_state["total_xp"])
    xp_state["level"] = new_level
    
    # Detect level up and award skill points
    level_up = new_level > old_level
    if level_up:
        points_to_add = (new_level - old_level) * SKILL_POINTS_PER_LEVEL
        xp_state["skill_points"] += points_to_add
    
    # Check for achievements
    new_achievements = check_achievements()
    
    # Save state
    save_state()
    
    return earned_xp, xp_state["multiplier"], level_up, new_level, new_achievements

# Custom progress bar style
class XPProgressBar(QProgressBar):
    def __init__(self, parent=None):
        super(XPProgressBar, self).__init__(parent)
        self.setTextVisible(True)
        self.setMinimumHeight(20)
        self.setStyleSheet("""
            QProgressBar {
                border: 1px solid #076329;
                border-radius: 5px;
                text-align: center;
                background-color: #f0f0f0;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1: 0, y1: 0.5, x2: 1, y2: 0.5, stop: 0 #5cb85c, stop: 1 #3e8f3e);
                border-radius: 5px;
            }
        """)

# Status bar widget
class XPStatus(QWidget):
    def __init__(self, parent=None):
        super(XPStatus, self).__init__(parent)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(10)
        
        # Level and XP text
        self.text_label = QLabel()
        self.text_label.setStyleSheet("font-weight: bold; color: #009900;")
        
        # Progress bar
        self.progress_bar = XPProgressBar()
        self.progress_bar.setFixedWidth(150)
        
        # Add widgets to layout
        self.layout.addWidget(self.text_label)
        self.layout.addWidget(self.progress_bar)
        
        self.setLayout(self.layout)
        self.update_text()
    
    def update_text(self):
        level, progress, xp_needed = calculate_level(xp_state["total_xp"])
        self.text_label.setText(f"Level: {level} | XP: {xp_state['daily_xp']} | Total: {xp_state['total_xp']} | Multiplier: x{xp_state['multiplier']:.1f} | Streak: {xp_state['streak']}")
        self.progress_bar.setValue(progress)
        self.progress_bar.setFormat(f"Level {level+1}: {progress}%")

# Update display
def update_display(*args):
    if hasattr(mw, 'xp_status'):
        mw.xp_status.update_text()

# Show stats
def show_stats():
    load_state()
    level, progress, xp_needed = calculate_level(xp_state["total_xp"])
    
    stats = f"""
    <h2>Anki XP Stats</h2>
    <table>
        <tr><td>Level:</td><td><b>{level}</b></td></tr>
        <tr><td>Progress to Level {level+1}:</td><td><b>{progress}%</b></td></tr>
        <tr><td>XP Needed for Level {level+1}:</td><td><b>{xp_needed}</b></td></tr>
        <tr><td>Daily XP:</td><td><b>{xp_state['daily_xp']}</b></td></tr>
        <tr><td>Total XP:</td><td><b>{xp_state['total_xp']}</b></td></tr>
        <tr><td>Current Streak:</td><td><b>{xp_state['streak']} cards</b></td></tr>
        <tr><td>Current Multiplier:</td><td><b>x{xp_state['multiplier']:.1f}</b></td></tr>
        <tr><td>High Score:</td><td><b>{xp_state['high_score']}</b></td></tr>
        <tr><td>Skill Points Available:</td><td><b>{xp_state['skill_points']}</b></td></tr>
    </table>
    
    <h3>XP Rules</h3>
    <ul>
        <li>Again: {BASE_XP_AGAIN} XP</li>
        <li>Hard: {BASE_XP_HARD} XP</li>
        <li>Good: +{BASE_XP_GOOD} XP</li>
        <li>Easy: +{BASE_XP_EASY} XP</li>
        <li>Consecutive Good/Easy answers increase your multiplier!</li>
        <li>Maximum multiplier: x{MAX_MULTIPLIER:.1f}</li>
    </ul>
    
    <h3>Level System</h3>
    <ul>
        <li>Your level is based on your total XP</li>
        <li>Each level requires more XP than the previous</li>
        <li>You earn {SKILL_POINTS_PER_LEVEL} skill point(s) per level</li>
        <li>Maximum level: {MAX_LEVEL}</li>
    </ul>
    """
    showInfo(stats, title="Anki XP Stats", textFormat="rich")

# Setup status bar
def setup_status_bar():
    mw.xp_status = XPStatus()
    mw.statusBar().addPermanentWidget(mw.xp_status)

# Setup menu
def setup_menu():
    menu = QMenu("XP System", mw)
    
    # Stats action
    stats_action = QAction("View XP Stats", mw)
    stats_action.triggered.connect(show_stats)
    menu.addAction(stats_action)
    
    # Reset action
    reset_action = QAction("Reset XP Data", mw)
    reset_action.triggered.connect(reset_state)
    menu.addAction(reset_action)
    
    # Add to main menu
    mw.form.menuTools.addMenu(menu)

# Hook for answering cards
def on_answer(*args):
    # Extract the ease value (should be the last argument)
    try:
        ease = args[-1]
        if not isinstance(ease, int) or ease < 1 or ease > 4:
            return
        
        load_state()
        earned_xp, multiplier, level_up, new_level, new_achievements = calculate_xp(ease)
        
        # Prepare tooltip message
        message = ""
        
        # Add level up message if applicable
        if level_up:
            message += f"<div style='color: #FFD700; font-weight: bold;'>LEVEL UP! You are now level {new_level}!</div>"
            message += f"<div style='color: #FFD700;'>You earned {SKILL_POINTS_PER_LEVEL} skill point(s)!</div>"
        
        # Add XP message
        if earned_xp >= 0:
            message += f"<div style='color: #00AA00; font-weight: bold;'>+{earned_xp} XP (x{multiplier:.1f})</div>"
        else:
            message += f"<div style='color: #AA0000; font-weight: bold;'>{earned_xp} XP</div>"
        
        # Add achievement notifications
        for achievement in new_achievements:
            message += f"<div style='color: #FFD700; font-weight: bold;'>Achievement Unlocked: {achievement['icon']} {achievement['name']}</div>"
            message += f"<div style='color: #FFD700;'>+{achievement['reward_xp']} XP</div>"
        
        # Show tooltip
        tooltip_duration = 1500
        if level_up or new_achievements:
            tooltip_duration = 3000
        
        tooltip(message, period=tooltip_duration)
        
        # Update display
        update_display()
    except Exception as e:
        # Print error for debugging but don't show to user
        print(f"Error in on_answer: {str(e)}")

# Initialize add-on
def init():
    try:
        # Load data
        load_state()
        
        # Setup UI
        setup_status_bar()
        setup_menu()
        
        try:
            # Try to use direct method wrapping for more reliable answer detection
            from aqt.reviewer import Reviewer
            
            # Original _answerCard method
            original_answer_card = Reviewer._answerCard
            
            # Wrapped method
            def wrapped_answer_card(self, ease):
                # Call original method
                ret = original_answer_card(self, ease)
                
                # Process XP
                try:
                    load_state()
                    earned_xp, multiplier, level_up, new_level, new_achievements = calculate_xp(ease)
                    
                    # Prepare tooltip message
                    message = ""
                    
                    # Add level up message if applicable
                    if level_up:
                        message += f"<div style='color: #FFD700; font-weight: bold;'>LEVEL UP! You are now level {new_level}!</div>"
                        message += f"<div style='color: #FFD700;'>You earned {SKILL_POINTS_PER_LEVEL} skill point(s)!</div>"
                    
                    # Add XP message
                    if earned_xp >= 0:
                        message += f"<div style='color: #00AA00; font-weight: bold;'>+{earned_xp} XP (x{multiplier:.1f})</div>"
                    else:
                        message += f"<div style='color: #AA0000; font-weight: bold;'>{earned_xp} XP</div>"
                    
                    # Add achievement notifications
                    for achievement in new_achievements:
                        message += f"<div style='color: #FFD700; font-weight: bold;'>Achievement Unlocked: {achievement['icon']} {achievement['name']}</div>"
                        message += f"<div style='color: #FFD700;'>+{achievement['reward_xp']} XP</div>"
                    
                    # Show tooltip
                    tooltip_duration = 1500
                    if level_up or new_achievements:
                        tooltip_duration = 3000
                    
                    tooltip(message, period=tooltip_duration)
                    
                    # Update display
                    update_display()
                except Exception as e:
                    # Print error for debugging but don't show to user
                    print(f"Error in wrapped_answer_card: {str(e)}")
                
                return ret
            
            # Replace the method
            Reviewer._answerCard = wrapped_answer_card
            
            print("XP Add-on: Using method wrapping for answer detection")
        except:
            # Fall back to regular hooks if method wrapping fails
            addHook("reviewCleanup", update_display)
            addHook("showQuestion", update_display)
            addHook("showAnswer", update_display)
            addHook("afterReviewerAnswered", on_answer)
            
            print("XP Add-on: Using hooks for answer detection")
    except Exception as e:
        print(f"XP Add-on: Error during initialization: {str(e)}")

# Start the add-on
init()