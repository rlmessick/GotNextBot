from datetime import datetime
import operator
import os
from queue import Queue
from random import randint
import re
import time


from loguru import logger
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, ConversationHandler

class TeamInfo:
    def __init__(self, player, partner=None, team_number=-1):
        self._player = player.strip()
        self._partner = None
        if partner:
            self._partner = partner.strip()
        self._wins = 0
        self._losses = 0
        self.default = "*"
        self._team_number = int(team_number)
        self._current_win_streak = 0
        self._previous_win_streak = 0
        self._best_win_streak = 0
        self._previous_best_win_streak = 0
        self.group = set()
        self.teams_played = set()

    @property
    def best_win_streak(self):
        return self._best_win_streak
    
    @property
    def win_streak(self):
        return self._current_win_streak

    @property
    def team_number(self):
        return int(self._team_number)

    @property
    def player(self):
        return self._player.capitalize()
    
    @player.setter
    def player(self, player):
        self._player = player.strip()

    @property
    def partner(self):
        if self._partner is not None:
            return self._partner.capitalize()
        return self.default

    @partner.setter
    def partner(self, partner):
        self._partner = partner.strip()

    @property
    def wins(self):
        return int(self._wins)
    
    @property
    def losses(self):
        return int(self._losses)
    
    def reset(self):
        self._wins = 0
        self._losses = 0
        self._current_win_streak = 0
        self._previous_win_streak = 0
        self._best_win_streak = 0
        self._previous_best_win_streak = 0
        self._group.clear()

    def edit_wins(self, amount=1):
        self._wins = self._wins + amount
        
        if self._wins < 0:
            self._wins = 0
        if amount < 0:
            if self.win_streak >= self.best_win_streak:
                self._best_win_streak = self._previous_best_win_streak

            if abs(amount) == 1:
                self._current_win_streak = self._previous_win_streak
            else:
                self._current_win_streak = 0
        else:
            self._previous_win_streak = self._current_win_streak
            self._current_win_streak = self._current_win_streak + amount

            if self._current_win_streak >= self._best_win_streak:
                self._previous_best_win_streak = self.best_win_streak
                self._best_win_streak = self._current_win_streak
    
    def edit_losses(self, amount=1):
        self._losses = self._losses + amount
        if self.losses < 0:
            self._losses = 0
        if amount < 0:
            self._best_win_streak = self._previous_win_streak
        else:
            self._previous_win_streak = self._current_win_streak

            if self._current_win_streak >= self._best_win_streak:
                self._previous_best_win_streak = self.best_win_streak
                self._best_win_streak = self._current_win_streak

            self._current_win_streak = 0
        
    def equals(self, team):
        match = False
        if team is None:
            return match
        if self.team_number is team.team_number:
            if self.player.lower() == team.player.lower():
                if self.partner.lower() == team.partner.lower():
                    match = True
        return match
    
    @property
    def win_percentage(self):
        """Returns the win percentage"""
        games_played = self.wins + self.losses
        win_percentage = 0
        if games_played > 0 and self.wins > 0:
            win_percentage = float((self.wins/games_played) * 100)
            logger.debug(f"Win percentage full: {win_percentage}")
        return win_percentage

    def full_details(self, tag_team_members=False):
        games_played = self.wins + self.losses
        win_percentage = int(self.win_percentage)
        if tag_team_members:
            tag_team = self.tag_team_members()
            details = f"{self.team_number:4d} | {self.best_win_streak:3d} | {win_percentage:4d}% | {self.wins:4d} | {self.losses:4d} | {tag_team}"
        else:
            details = f"{self.team_number:4d} | {self.best_win_streak:3d} | {win_percentage:4d}% | {self.wins:4d} | {self.losses:4d} | {str(self)}"
        logger.debug(details)
        return details

    def info(self):
        """Returns all information about a team"""
        games_played = self.wins + self.losses
        win_percentage = self.win_percentage
        info = (
            f"TEAM {self.team_number}\n"
            f"{str(self)}\n"
            f"Record: {self.wins} W  - {self.losses} L\n"
            f"Win Percentage: {win_percentage}\n"
            f"Group(s): {list(self.group)}\n"
            f"Team(s) Played: {list(self.teams_played)}\n"
            )
        return info
    @property
    def record(self):
        return f"{self.team_number} | {self.wins} - {self.losses}"

    def tag_team_members(self):
        return f"@{self.player} & @{self.partner}"

    def team_number_details(self, seperator="|"):
        details = f"{self.team_number:2d} {seperator} {str(self)}"
        return details

    def __str__(self):
        return f"{self.player} & {self.partner}"

class WaitList:
    def __init__(self):
        self._queue = Queue(maxsize=0)

    def add(self, team):
        if isinstance(team, TeamInfo):
            if team in self._queue.queue:
                return False
            self._queue.put(team)
            return True
        return False
        
    def get(self, count=1):
        if self.size < count:
            raise Exception("ERROR: Not enough team(s) on the waitlist!")
        
        teams = []
        for _ in range(count):
            team = self._queue.get_nowait()
            teams.append(team)
        return teams

    def clear(self):
        self._queue.queue.clear()

    def in_queue(self, proposed_team):
        if proposed_team in self._queue.queue:
            return True
        return False

    def remove_team(self, team_to_remove):
        try:
            self._queue.queue.remove(team_to_remove)
        except ValueError:
            raise ValueError(f"Error team {team_to_remove.team_number_details()} is not on the waitlist")
        
    @property
    def size(self):
        return self._queue.qsize()
    
    def info(self):
        teams = []
        first_team = True
        for team in self._queue.queue:
            if first_team:
                teams.append(f"@{team.player} & @{team.partner}")
                first_team = False
            else:
                teams.append(str(team))
        return teams

class Table:
    def __init__(self, team1, team2, table_number=-1, invite_code=None):
        if team1.equals(team2):
            raise Exception("Team is playing themselves.  Do you need to correct a table? /correcttable <table_number>, team1, team2 ")
        self.invite_code = invite_code.upper()
        self._team1 = team1
        self._team2 = team2
        self._winner = "*"
        self._loser = "*"
        self._next_team = "*"
        self._next_invite_code = "*"
        self._game_status = True
        self._table_number = int(table_number)
    
    @property
    def table_number(self):
        return self._table_number
    
    def short_info(self):
        if isinstance(self._loser, str):
            return (f"{self._table_number} | {self.invite_code} | {self._team1.team_number} vs {self._team2.team_number} | "
                    f"{self._winner} | {self._loser} | {self._next_invite_code} | {self._next_team}")

        next_team = "Table Destroyed"
        if isinstance(self._next_team, TeamInfo):
            next_team = self._next_team.team_number
        return (f"{self._table_number} | {self.invite_code} | {self._team1.team_number} vs {self._team2.team_number} | "
                f"{self._winner.team_number} | {self._loser.team_number} | "
                f"{self._next_invite_code} | {next_team}")

    def __str__(self):
        seperator = ":"
        return (f"{self._table_number:3d} | {self.invite_code:10s} | {self._team1.team_number_details(seperator) } vs {self._team2.team_number_details(seperator)}\n"
                f"    | {str(self._winner):25s} | {str(self._loser):25s}\n"
                f"    | {self._next_invite_code:10s} | {str(self._next_team):25s}")

    def final(self, winner, next_team, invite_code=None):
        if self._team1.equals(winner):
            self._winner, self._loser = self._team1, self._team2
            self._team1.edit_wins()
            self._team2.edit_losses()
        else:
            self._winner, self._loser = self._team2, self._team1
            self._team2.edit_wins()
            self._team1.edit_losses()
        self._team1.teams_played.add(self._team2.team_number)
        self._team2.teams_played.add(self._team1.team_number)

        self._next_team = next_team
        self._game_status = False
        self._next_invite_code = ""
        if invite_code:
            self._next_invite_code = invite_code.upper()
  
    @property
    def teams(self):
        return [self._team1, self._team2]
    @property
    def active(self):
        return self._game_status

class GotNextBot:
    
    def __init__(self, token):
        self._updater = Updater(token, use_context=True)
        self._groups = set()
        self._teams = list()
        self._tables = list()
        self._max_tables = 0
        self._waitlist = WaitList()
        self._action = list()
        self._messages = list()
        self._get_number_result, self._get_string_result = range(2)
        self._team_number = 0
        self.date_query = "%Y-%m-%d"
        self._table_file = f"Tables_{datetime.today().strftime(self.date_query)}.txt"
        self._team_file = f"Teams_{datetime.today().strftime(self.date_query)}.txt"
        self._game_play_type = "rise"
    
    def load_data(self, team_file=None, table_file=None):
        """Load up previous data"""
        if team_file is not None:
            self._team_file = team_file
        if table_file is not None:
            self._table_file = table_file

        # getting team list
        data = list()
        if os.path.exists(self._team_file):
            with open(self._team_file, "r") as read_file:
                data = read_file.readlines()
            # "0 | Toni &  ___"
        for entry in data:
            logger.debug(f"")
            team_number = int(entry.split("|")[0])
            team = entry.split("|")[1]
            player = team.split("&")[0]
            partner = team.split("&")[1]
            found = False
            logger.debug(f"Team Number: {team_number}, Player:{player}, Partner: {partner}")
            
            for team in self._teams:
                if team.team_number is team_number:
                    found = True
                    team.player = player
                    team.partner = partner
            if not found:
                team = TeamInfo(player=player, partner=partner, team_number=team_number)
                self._teams.append(team)
        
        # data = list()
        # if os.path.exists(self._table_file):
        #     with open(self._table_file, "r") as read_file:
        #         data = read_file.readlines()
        # table number | invite code | team1 # vs team2 # | winner # | loser # | next invite code | next team #

    def are_parameters_set(self, message, parameters_expected=1, expect_subcommand=True):
        self._messages.clear()
        try:
            x = command = message.split(" ")
            logger.debug(x)

            command = message.split(" ")[0]
            if expect_subcommand:
                subcommand = message.split(" ")[1]
                subcommand = subcommand.strip()
                parameters_set = message.split(subcommand)[1]
            else:
                parameters_set = message.split(command)[1]
                subcommand = ""
        except IndexError:
            parameters_set = []
            subcommand = ""
            command = message[1:]
        
        logger.debug(f"Message: {message}, command: {command}, subcommand: {subcommand} parameters: {parameters_set}")

        if parameters_set:
            self._messages = parameters_set.split(",")
            for message in self._messages:
                message = message.strip()

        if expect_subcommand:
            self._messages.insert(0, subcommand)
            parameters_expected += 1
        logger.debug(f"Parameters: {self._messages}")
        if len(self._messages) >= parameters_expected:
            return True
        return False

    def help(self, update, context):
        """/help (help menu)"""
        update.message.reply_text(
            "/add   <team_number> -> Adds a team to the waitlist\n"
            "/clear <subcommand> -> Actions to erasing items\n"
            "/list  <subcommand> -> Acions that concern the Waitlist\n"
            "/play  <subcommand> -> Changes the game play of an event"
            "/next  <winning_team_number>, <invite_code> [<add_the_losing_team_to_waitlist>] -> Puts a new team to the table\n"
            "/stats <tag_all_teams>-> Print all the teams statistics\n"
            "/table <subcommand> -> Acions that concern Table(s)\n"
            "/team <subcommand> -> Acions that concern Team(s)\n"
            "/quit -> Prints final Results"
            "/help\n"
        )
        return ConversationHandler.END

    def check_output(self, message, update):
            result = False
            if len(message) > 3000:
                update.message.reply_text(message)
                result = True
            return result

    def next_team_to_table(self, update, context):
        self.are_parameters_set(message=update.message.text, expect_subcommand=False)
        self._messages.insert(0, "next")
        self._next_team(update)
        return ConversationHandler.END

    def add_waitlist(self, update, context):
        """/add (Adds a team waitlist)"""
        if not self.are_parameters_set(message=update.message.text, expect_subcommand=False):
            update.message.reply_text(f"ERROR: Not enough paramters.  /add <team_number>")
            return ConversationHandler.END
        try:
            team_number = int(self._messages[0])
            for team in self._teams:
                if team.team_number is team_number:
                    logger.debug(f"Team number {team_number}\nteam selected{str(team)}")
                    self._add_to_waitlist(update=update, team=team)
                    return ConversationHandler.END
        except ValueError:
            msg = f"ERROR: Value provided is not a number.  Team Number: {self._messages[0]}"
            logger.exception(msg)
            update.message.reply_text(msg)

        msg = f"ERROR: Team #{team_number} is a not found."
        logger.error(msg)
        update.message.reply_text(msg)

        return ConversationHandler.END

    def print_stats(self, update, context):
        self.are_parameters_set(message=update.message.text)
        self._get_stats(update)
    
    def _commands_get_parameters(self, update, default=""):
        self.are_parameters_set(message=update.message.text, parameters_expected=0)
        
        if self._messages[0] == "":    
            self._messages[0] = default
        
    # PRINT COMMANDS
    # defaults to stats
    def print_commands(self, update, context):
        """/print all commands that display print items back to the user"""
        self._commands_get_parameters(update, "active")
            
        action = self._messages[0]
        action = action.lower()

        logger.debug(f"Action: {action}")

        if "all" in action:
            self._get_all_info(update)
        elif "active" in action:
            self._print_tables(update=update, active_only=True)
        elif "group" in action:
            self._get_groups(update)
        elif "help" in action:
            self._help_print_commands(update)
        elif "team" in action:
            self._get_teams(update=update)
        elif "table" in action:
            self._get_tables(update)
        elif "stat" in action:
            self._get_stats(update)
        elif "list" in action:
            self._get_waitlist(update)
        else:
            update.message.reply_text(f"ERROR:  No such subcommand {action}.  See 'print help' for more details")
        return ConversationHandler.END
    
    def _print_tables(self, update, active_only=False, team_number=None):
        space = " "
        table_message = f"---------- Tables ----------\n"
        table_message = table_message + f"Number of Tables: {len(self._tables)}\n"
        active_tables = 0
        for table in self._tables:
            if table.active:
                active_tables = active_tables + 1

        if active_tables > self._max_tables:
            table_message = table_message + f"WARNING: Next {self._max_tables - active_tables} table(s) will be torn down.\n"
            table_message = table_message + f"There are {self._max_tables} table(s) for future game play!!!\n"
        table_message = table_message + f"Number of Active Tables: {active_tables}\n"
        table_message = table_message + f"#{space*3}| Invite code | Matchup\n  | Winner{space*19} | Loser\n    | Next code | Next Team\n"

        for table in self._tables:
            if active_only and not table.active:
                continue
            if team_number is not None:
                logger.debug(f"team number {team_number},  team 1 {table._team1.team_number}  team 2 {table._team2.team_number}")
                if table._team1.team_number is not team_number and table._team2.team_number is not team_number:
                    logger.debug("skipping table")
                    continue
            table_message = table_message + f"{str(table)}\n"
            table_message = table_message + f"-"*50 +"\n"
            if self.check_output(message=table_message, update=update):
                table_message = f""
        update.message.reply_text(table_message)

    def _get_groups(self, update):
        msg = f"Groups: {list(self._groups)}"
        update.message.reply_text(msg)
        logger.debug(msg)

    def _get_tables(self, update):
        """/printtables (prints all the tables)"""
        team_number = None
        try:
            if len(self._messages) > 2:
                team_number = int(self._messages[2])
            logger.debug(f"team number -> {team_number}")
        except ValueError:
            msg = f"ERROR: Value provided is not a number.  Team Number: {self._messages[0]}"
            logger.exception(msg)
            update.message.reply_text(msg)

        self._print_tables(update, team_number=team_number)

    def _get_stats(self, update):
        """/print stats (prints all teams statistics)"""
        tag_team_members = False
        if len(self._messages) > 1:
            tag_team_members = True
        self._get_teams(update=update, stats=True, tag_team_members=tag_team_members)

    def _get_all_info(self, update):
        self._get_teams(update=update, stats=True)
        self._get_waitlist(update=update)
        self._print_tables(update=update)

    def _help_print_commands(self, update):
        """help command for the print command"""
        help = (f""
            "all     -> Displys all table, teams, and waitlist\n"
            "active  -> Displays all tables in use\n"
            "groups  -> Displays all the groups of a team\n"
            "list    -> Displays the waitlist\n"
            "tables [team number] -> Displays all the tables for the game or for an individual team\n"
            "teams   -> Displays all the teams\n"
            "help    -> Displays commands for the print command\n")
        update.message.reply_text(help)
    
    # LIST COMMANDS
    # defaults to printing waitlist
    def list_commands(self, update, context):
        """/list all commands that deal with the waitlist"""
        self._commands_get_parameters(update, "get")
        
        action = self._messages[0]
        action = action.lower()
        logger.debug(action)
        logger.debug(type(action))
        if "add" in action:
            if len(self.messages) < 2:
                update.message.reply_text("ERROR: Not enough parameters.  /list add <team number>")
                return
            try:
                team_number = int(self._messages[1])
                team_found = False
                for team in self._teams:
                    if team.team_number is team_number:
                        logger.debug(f"Team number {team_number}\nteam selected{str(team)}")
                        self._add_to_waitlist(update=update, team=team)
                        team_found = True
                        break
                if not team_found:
                    msg = f"ERROR: Team #{team_number} is a not found."
                    logger.error(msg)
                    update.message.reply_text(msg)

            except ValueError:
                msg = f"ERROR: Value provided is not a number.  Team Number: {self._messages[0]}"
                logger.exception(msg)
                update.message.reply_text(msg)

        elif "del" in action or "remove" in action:
            self._remove_team_from_waitlist(update)
        elif "get" in action:
            self._get_waitlist(update)
        elif "help" in action:
            self._help_list_commands(update)
        else:
            update.message.reply_text(f"ERROR:  No such subcommand {action}.  See 'list help' for more details")

        return ConversationHandler.END

    def _add_to_waitlist(self, update, team, print_waitlist=True):
        if self._waitlist.add(team):
            waitlist = self._waitlist.info()
            logger.debug(f"Waitlist: {waitlist}")
            if print_waitlist:
                self._get_waitlist(update=update)
        else:
            msg = f"ERROR: Team: {str(team)} was already on the list.  Not adding this team."
            update.message.reply_text(msg)
            logger.error(msg)
        
    def _remove_team_from_waitlist(self, update):
        """/list remove (for the waitlist)"""
        if len(self._messages) < 2:
            update.message.reply_text("ERROR: Not enough parameters.  /list remove <team number>")
            return 
        team_number = int(self._messages[1])
        for team in self._teams:
            if team.team_number is team_number:
                team_to_remove = team
        try:
            self._waitlist.remove_team(team_to_remove=team_to_remove)
            update.message.reply_text(f"Removed team {str(team_to_remove)} from the waitlist.")
        except ValueError as msg:
            logger.exception(msg)
            update.message.reply_text(msg)
         
    def _get_waitlist(self, update):
        waitlist_message = f"---------- Waitlist ----------\n"
        waitlist_message = waitlist_message + f"Number of teams on the waitlist: {self._waitlist.size}\n"
        waitlist = self._waitlist.info()
        counter = 1
        for team in waitlist:
            waitlist_message += f"{counter} | {str(team)}\n"
            if self.check_output(message=waitlist_message, update=update):
                waitlist_message = f""
            
            counter = counter + 1
        update.message.reply_text(waitlist_message)

    def _help_list_commands(self, update):
        """help command for the list command"""
        help = (f""
            "add     [team_number]-> Adds a team to the waitlist\n"
            "delete  [team_number]-> Removes a team from the waitlist\n"
            "get     -> Displays the waitlist\n"
            "help    -> Displays commands for the list command\n")
        update.message.reply_text(help)

    # TEAM COMMANDS
    def team_commands(self, update, context):
        """/team all commands that deal with the team object"""
        self._commands_get_parameters(update, "help")
            
        action = self._messages[0]
        action = action.lower()

        if "create" in action:
            self._create_team(update)
        elif "delete" in action:
            self._delete_team(update)
        elif "info" in action:
            self._get_team_info(update)
        elif "group" in action:
            self._group_subcommand(update)
        elif "loss" in action:
            self._update_wins_losses(update, change_wins=False)
        elif "table" in action:
            self._get_teams_tables(update)
        elif "update" in action:
            self._update_team(update)
        elif "win" in action:
            self._update_wins_losses(update, change_wins=True)
        elif "help" in action:
            self._help_team_commands(update)
        else:
            update.message.reply_text(f"ERROR:  No such subcommand {action}.  See 'team help' for more details")

        return ConversationHandler.END

    def _group_subcommand(self, update):
        if len(self._messages) < 4:
            update.message.reply_text("ERROR: Not enough parameters: /team group <team_number>, <add|delete>, <group>")
            return
        try:
            msg  = ""
            team_found = False
            team_number = int(self._messages[1])
            action = self._messages[2]
            action = action.lower()
            group = self._messages[3]

            for team in self._teams:
                if team.team_number is team_number:
                    if "add" in action:
                        self._groups.add(group)
                        team.group.add(group)
                        update.message.reply_text(f"Team {team_number} has been added to group: {group}")
                    elif "del" in action:
                        try:
                            team.group.remove(group)
                            update.message.reply_text(f"Team {team_number} has been removed from group: {group}")
                        except KeyError:
                            msg = f"Team {team_number} was never apart of group: {group}"
                            logger.error(msg)
                            update.message.reply_text(msg)
                    else:
                        msg = f"ERROR: Group action: {action} not found!  Valid actions are ADD or DELETE"
        except ValueError:
            update.message.reply_text(f"Invalid Digit: Team Number: {self._messages[0]}, Amount: {self._messages[1]}")
            logger.exception("Invalid Digit")

    def _get_teams_tables(self, update):
        try:
            team_number = int(self._messages[1])
            team_found = False
            
            for team in self._teams:
                if team.team_number is team_number:
                    self._print_tables(update, active_only=False, team_number=team_number)
                    team_found = True
                    break
            if not team_found:
                msg = f"ERROR: Team #{team_number} was not found"
                logger.error(msg)
            update.message.reply_text(msg) 
        except ValueError:
            update.message.reply_text(f"Invalid Digit: Team Number: {self._messages[0]}, Amount: {self._messages[1]}")
            logger.exception("Invalid Digit")
    
    def _create_team(self, update):
        """/createteam (Creates a team)"""
        def is_number_in_use(number):
            for team in self._teams:
                if team.team_number is number:
                    return True
            return False

        if len(self._messages) < 2:
            update.message.reply_text("ERROR: Not enough parameters: /team create player[, player, team_number]")
            return
        
        logger.debug(f"Parameters: {self._messages}")
        if "&" in self._messages[1]:
            parameters = self._messages[1].split(" & ")
            try:
                team_number = self._messages[2]
            except ValueError:
                team_number = self._team_number
            self._messages[1] = parameters[0]
            self._messages[2] = parameters[1]
            self._messages[3] = team_number

        partner = None
        player = self._messages[1]
        team_number = self._team_number
        is_team_number = False

        if len(self._messages) > 2:
            partner = self._messages[2]

        if len(self._messages) > 3:
            try:
                team_number = int(self._messages[3])
                is_team_number = True
            except ValueError:
                msg = f"ERROR: Team number provided is not a number.  Value: {self._messages[3]}"
                logger.exception(msg)
                update.message.reply_text(msg)
                return

        # if number is already taken and this number was provide by a person
        is_used = is_number_in_use(number=team_number)
        if  is_used and is_team_number:
            msg = f"ERROR: Team number:{team_number} is already in use."
            logger.error(msg)
            update.message.reply_text(msg)
            return

        # Lets find a number to use:
        while is_used:
            self._team_number = self._team_number + 1
            team_number = self._team_number
            is_used = is_number_in_use(number=team_number)

        # add team
        team = TeamInfo(player=player, partner=partner, team_number=team_number)
        if not is_team_number:
            self._team_number = self._team_number + 1
        self._teams.append(team)
        self._teams = sorted(self._teams, key=operator.attrgetter("_team_number"))
        msg = f"TEAM CREATED:\n# | Team\n{team.team_number_details()}"
        update.message.reply_text(msg)
        logger.info(msg)
        with open(self._team_file, "a") as write_file:
            write_file.write(f"{team.team_number_details()}\n")

    def _update_team(self, update):
        """/editteam (Edit names in a team)"""
        if len(self._messages) < 3:
            msg = f"ERROR: Incorrect parameters /team update <team_number>, player[,player]\n"
            msg = msg + f"Parameters: {self._messages}"
            logger.error(msg)
            update.message.reply_text(msg)
            return 
        try:
            team_number = int(self._messages[1])
            team_found = False
            player1 = self._messages[2]
            player2 = None
            if len(self._messages) > 3:
                player2 = self._messages[3]
            for team in self._teams:
                if team.team_number is team_number:
                    team_found = True
                    team.player = player1
                    team.partner = player2
                    msg = f"Team has been modified {str(team)}"
                    update.message.reply_text(msg)
                    logger.debug(msg)
                    with open(self._team_file, "a") as write_file:
                        write_file.write(f"{team.team_number_details()}\n")
            if not team_found:
                msg = f"ERROR: Team number: {team_number}, Not Found"
                update.message.reply_text(msg)
                logger.error(msg)
        except IndexError:
            update.message.reply_text(f"Invalid Digit: Team Number: {self._messages[1]}")
            logger.exception("Invalid team number")
        except Exception:
            logger.exception("Whats going on!!!")

    def _update_wins_losses(self, update, change_wins):
        try:
            team_number = int(self._messages[1])
            amount = 1
            if len(self._messages) > 2:
                amount = int(self._messages[2])
            for team in self._teams:
                if team.team_number is team_number:
                    if change_wins:
                        old_wins = team.wins
                        team.edit_wins(amount=amount)
                        new_wins = team.wins
                        update.message.reply_text(f"Team: {str(team)} changed wins from {old_wins} to {new_wins}")
                    else:
                        old_losses = team.losses
                        team.edit_losses(amount=amount)
                        new_losses = team.losses
                        update.message.reply_text(f"Team: {str(team)} changed losses from {old_losses} to {new_losses}")
        except ValueError:
            update.message.reply_text(f"Invalid Digit: Team Number: {self._messages[0]}, Amount: {self._messages[1]}")
            logger.exception("Invalid Digit")
    
    def _delete_team(self, update):
        try:
            msg  = ""
            team_found = False
            team_number = int(self._messages[1])
            for team in self._teams:
                if team.team_number is team_number:
                    self._teams.remove(team)
                    team_found = True
                    msg = f"Team #{team_number} has been removed"
                    logger.debug(msg)
                    break
            if not team_found:
                msg = f"ERROR: Team #{team_number} was not found"
                logger.error(msg)
            update.message.reply_text(msg) 
        except ValueError:
            update.message.reply_text(f"Invalid Digit: Team Number: {self._messages[0]}, Amount: {self._messages[1]}")
            logger.exception("Invalid Digit")

    def _get_team_info(self, update):
        try:
            team_found = False
            team_number = int(self._messages[1])
            for team in self._teams:
                if team.team_number is team_number:
                    msg = team.info()
                    team_found = True
            if not team_found:
                msg = f"ERROR: Team #{team_number} was not found"
                logger.error(msg)
            update.message.reply_text(msg)
        except ValueError:
            update.message.reply_text(f"Invalid Digit: Team Number: {self._messages[0]}, Amount: {self._messages[1]}")
            logger.exception("Invalid Digit")

    def _help_team_commands(self, update):
        """help command for the team command"""
        help = (f""
            "create  <team_member> [, <team_member>, <team_number>]   -> Creates a team\n"
            "delete  <team_number> -> Deletes the team\n"
            "group   <team_number> -> Displays all groups associated with a team\n"
            "info    <team_number> -> Displays all information about a team\n"
            "losses  <team_number> [, <amount>] -> Edits a team's losses\n"
            "table   <team_number> -> Displays all tables associated with a team\n"
            "update  <team_number> <team_member> [, <team_member>]-> Editss a team's member(s)\n"
            "wins    <team_number> [, <amount>] -> Edits a team's wins\n"
            "help    -> Displays commands for the team command\n")
        update.message.reply_text(help)

    # TABLE COMMANDS
    def table_commands(self, update, context):
        """/table all commands that deal with the table object"""
        self._commands_get_parameters(update, "help")

        action = self._messages[0]
        action = action.lower()

        if "create" in action:
            self._create_table(update)
        elif "act" in action:
            self._print_tables(update=update, active_only=True)
        elif "all" in action:
            self._print_tables(update)
        elif "del" in action:
            self._remove_table(update)
        elif "update" in action:
            self._update_table(update)
        elif "next" in action:
            self._next_team(update)
        elif "help" in action:
            self._help_table_commands(update)
        else:
            update.message.reply_text(f"ERROR:  No such subcommand {action}.  See 'table help' for more details")

        return ConversationHandler.END

    def _new_table(self, update, teams, invite_code, winners_kept=False):
        # Create the table
        table_number = len(self._tables)
        table = Table(team1=teams[0], team2=teams[1], invite_code=invite_code, table_number=table_number)

        # Write it to a file
        with open(self._table_file, "a") as file_writer:
            file_writer.write(f"{table.short_info()}\n") 

        table_message = f""
        if not winners_kept:
            table_message += f"---------- Table Created -----------\n"
            tag_team = table.teams[0].tag_team_members()
            table_message += f"{tag_team} go to table {table.invite_code}\n"
        tag_team = table.teams[1].tag_team_members()
        table_message += f"{tag_team} go to table {table.invite_code}\n"
        update.message.reply_text(table_message)
        
        self._tables.append(table)

    def _create_table(self, update):
        """/table create (Creates a table and add to gameplay)"""
        if len(self._messages) < 1:
            update.message.reply_text("ERROR: Not enough parameters.  /table create <invite code>")
        
        # adding another table to gameplay
        self._max_tables = self._max_tables + 1
        invite_code = ""
        if self._messages:
            invite_code = self._messages[1]
        
        logger.debug(f"Invite code is {invite_code}")
        try:
            teams = self._waitlist.get(count=2)
            self._new_table(update=update, teams=teams, invite_code=invite_code)
            
        except Exception as msg:
            logger.exception("Failure!!!")
            update.message.reply_text(f"{msg}")
        
    def _update_table(self, update):
        """/table update <tablenumber> <table_number>, <team number>, <team_number>[, <invite code>, <winning_team_number>"""
        if len(self._messages) < 4:
            update.message.reply_text("ERROR: Not enough parameters.  /edittable <table_number>, <team number>, <team_number>[, <invite code>, <winning_team_number>")
            return
        try:
            table_number = int(self._messages[1])
            team_1_number = int(self._messages[2])
            team_2_number = int(self._messages[3])
            team_1 = None
            team_2 = None
            invite_code = None
            winning_team_number = None
            winning_team = None

            if len(self._messages) > 4:
                invite_code = self._messages[4]
            if len(self._messages) > 5:
                winning_team_number = int(self._messages[5])

            logger.debug(f"Team Number 1: {team_1_number} Team 2: {team_2_number}  Invite Code:{invite_code} Winning Team Number {winning_team_number}")
            
            for team in self._teams:
                if team.team_number is team_1_number:
                    team_1 = team
                if team.team_number is team_2_number:
                    team_2 = team
                if winning_team_number is not None:
                    if winning_team_number is team.team_number:
                        winning_team = team

            if team_1 is None or team_2 is None:
                msg = f"ERROR: A team was not found. Team 1: {team_1_number}, Team 2 {team_2_number}"
                update.message.reply_text(msg)
                logger.error(msg)
                return
            
            if team_1.equals(team_2):
                msg = f"ERROR: Team numbers are the same. Team 1: {team_1_number}, Team 2 {team_2_number}"
                update.message.reply_text(msg)
                logger.error(msg)
                return

            table_found = False
            for table in self._tables:
                if table_number is table.table_number:
                    table_found = True
                    table._team1 = team_1
                    table._team2 = team_2
                    if invite_code is not None:
                        table.invite_code = invite_code
                    if not table.active:
                        if winning_team is not None and not table._winner.equals(winning_team):
                            table._winner.edit_wins(-1)
                            table._loser.edit_losses(-1)
                            if not table._winner.equals(winning_team):
                                if table._team1.equals(winning_team):
                                    table._team1.edit_wins(1)
                                    table._team2.edit_losses(1)
                                    table._winner = team_1
                                    table._loser = team_2

                                elif table._team2.equals(winning_team):
                                    table._team2.edit_wins(1)
                                    table._team1.edit_losses(1)
                                    table._winner = team_2
                                    table._loser = team_1
                                
                                else:
                                    msg = (f"ERROR: Winning team is not aprt of table {table_number}. Team 1: {team_1_number}, "
                                            "Team 2: {team_2_number}, Winning Team: {winning_team_number}")

                                    update.message.reply_text(msg)
                                    logger.error(msg)

                                    # Restore wins and loses for the original teams
                                    table._winner.edit_wins(1)
                                    table._loser.edit_losses(1)

                                    return
                                update.message.reply_text("WARNING: Changed table results on a non active table.")

                    update.message.reply_text(f"SUCCESS: Table {table_number}:  has been updated!")
                    logger.info(f"SUCCESS: Table {table_number}:  has been updated!")

                    # Write it to a file
                with open(self._table_file, "a") as file_writer:
                    file_writer.write(f"{table.short_info()}\n") 

            if not table_found:
                msg = f"ERROR: Table number {table_number} was not found."
                update.message.reply_text(msg)
                logger.error(msg)
            
        except ValueError:
            msg = f"ERROR:  A value was not a number.  Table Number: {self._messages[1]}  Team 1 #: {self._messages[2]} Team 2 #: {self._messages[3]}"
            if len(self._messages) > 5:
                msg = msg + f" Invite Code: {self._messages[4]}"
            if len(self._messages) > 6:
                msg = msg + f" Winning Team #: {self._messages[5]}"
            update.message.reply_text(msg)
            logger.exception(msg)
  
    def _remove_table(self, update):
        """/removetable (remove a table)"""
        if self._max_tables < 1:
            update.message.reply_text("No tables have been assigned.  Try again chump")
        else:
            self._max_tables = self._max_tables-1
            update.message.reply_text(f"Tables removed!! Remaining tables {self._max_tables}")
    
    def _next_team(self, update):
        """/next - gets a team from waitlist"""
        if len(self._messages) < 3:
            update.message.reply_text("ERROR: Not enough parameters.  /table next <winning_team_number>, <invite_code>[, <add_losing_team, defaults to yes>]")
        try:
            logger.debug(f"{self._messages}")
            team_number = int(self._messages[1])
            invite_code = self._messages[2]
            add_to_waitlist = "yes"
            if len(self._messages) > 3:
                add_to_waitlist = self._messages[3]

            winning_team = None
            for team in self._teams:
                if team.team_number is team_number:
                    winning_team = team
            
            if winning_team is None:
                raise Exception(f"ERROR: Team Number {team_number} not found")

            active_tables = 0
            next_team = None
            table_found = None

            logger.debug(f"Winning team is {str(winning_team)}  new invite code is {invite_code}")

            for table in self._tables:
                if table.active:
                    active_tables = active_tables + 1
            logger.debug(f"Active tables: {active_tables},  max tables: {self._max_tables}")

            for table in self._tables:
                # find the winning team
                if table.active and winning_team in table.teams:
                    table_found = table
                
                    if table_found.invite_code.strip() == invite_code.strip():
                        msg = f"WARNING:  Invite code is the same the previous game. Invite code {invite_code}"
                        update.message.reply_text(msg)
                        logger.warning(msg)

            if table_found is not None:
                # Getting the next team from waitlist for this table
                # create a new table
                if active_tables > self._max_tables:
                    update.message.reply_text(f"WARNING: This table is being destroyed.  Tables remaining {active_tables-1}")
                    logger.warning(f"Breaking down this table.  Tables remaining {active_tables}.  Max tables{self._max_tables}")
                    invite_code = "-------------"
                else:
                    next_team = self._waitlist.get()[0]
                    teams = [winning_team, next_team]
                    self._new_table(update=update, teams=teams, invite_code=invite_code, winners_kept=True)
                
                # displaying winning streak and finializing table
                winning_team_win_streak = winning_team.win_streak
                teams = table_found.teams
                teams.remove(winning_team)
                losing_team = teams[0]
                msg = f""
                if losing_team.win_streak > 3:
                    msg += f"{str(losing_team)} winning streak ends at {losing_team.win_streak} games\n"
                table_found.final(winner=winning_team, next_team=next_team, invite_code=invite_code)
                msg += f"{str(winning_team)} winning streak is at {winning_team.win_streak} game(s)\n"
                msg += f"{winning_team.record}\n{losing_team.record}\n"
                update.message.reply_text(msg)

                # add teams to waitlist
                if "yes" in add_to_waitlist.lower():
                    teams = table_found.teams
                    teams.remove(winning_team)
                    if active_tables > self._max_tables:
                        teams.insert(0, winning_team)
                    print_list = False
                    for team in teams:
                        if team is teams[-1]:
                            print_list = True
                        self._add_to_waitlist(update=update, team=team, print_waitlist=print_list)

                # Write it to a file
                with open(self._table_file, "a") as file_writer:
                    file_writer.write(f"{table_found.short_info()}\n") 
            else:
                raise Exception(f"ERROR: {str(winning_team)} are not playing.")
        except (ValueError, IndexError):
            logger.exception("Failure!!!")
            update.message.reply_text(f"Invalid team number: {team_number}")
        except Exception as msg:
            logger.exception("Failure!!!")
            update.message.reply_text(f"{msg}")
  
    def _get_teams(self, update, stats=False, tag_team_members=False):
        team_message = f"---------- Teams ----------\n"
        team_message = team_message + f"Number of teams: {len(self._teams)}\n"
        if stats:
            team_message = team_message + f"TM # | W.S | % | W | L | Team\n"

        else:
            team_message = team_message + f" # | Team\n"
        self._teams = sorted(self._teams, key=operator.attrgetter("_team_number"))
        for team in self._teams:
            if self.check_output(message=team_message, update=update):
                team_message = f""
            if stats:
                details = team.full_details(tag_team_members=tag_team_members)
                team_message = team_message + f"{details}\n"
            else:
                details = team.team_number_details()
                team_message = team_message + f"{details}\n"
        update.message.reply_text(team_message)
   
    def _help_table_commands(self, update):
        """help command for the table command"""
        help = (
            "active  -> Displys all active table(s)\n"
            "all     -> Displys all tables\n"
            "create  <invite_code> -> Creates a new table\n"
            "delete  -> Displays all tables in use\n"
            "next    <team_number>, <invite_code> [, <add_losing_team_to_waitlist>] -> Puts a new team from the waitlist to the winners table\n"
            "update  <table_number>, <team_number_1>, <team_number_2>[, <invite_code> [, <winner_team_number>]] -> Updates a table with correct details\n"
            "help    -> Displays commands for the table command\n"
            )
        update.message.reply_text(help)
    
    # CLEAR COMMANDS
    def clear_commands(self, update, context):
        """/clear all commands that deal with permently removing items in list"""
        self._commands_get_parameters(update, "help")
        
        action = self._messages[0]
        action = action.lower()

        if "all" in action:
            self._clear_everything(update)
        elif "group" in action:
            self._clear_groups(update)
        elif "list" in action:
            self._clear_waitlist(update)
        elif "table" in action:
            self._clear_tables(update)
        elif "team" in action:
            self._clear_teams(update)
        elif "help" in action:
            self._help_clear_commands(update)
        else:
            update.message.reply_text(f"ERROR:  No such subcommand {action}.  See 'clear help' for more details")

        return ConversationHandler.END

    def _clear_waitlist(self, update):
        """/clearwaitlist (clears the entire waitlist)"""
        self._waitlist.clear()
        update.message.reply_text("Waitlist cleared")
            
    def _clear_teams(self, update):
        """/clear teams: (clears all teams info)"""
        self._teams.clear()
        self._team_number = 0
        update.message.reply_text("Teams cleared")
    
    def _clear_tables(self, update):
        """/clear tables - clears all the tables and table history"""
        self._tables.clear()
        update.message.reply_text("Tables cleared")
    
    def _clear_groups(self, update):
        """/clear tables - clears the master group list"""
        self.groups.clear()
        update.message.reply_text("Tables cleared")

    def _clear_waitlist(self, update):
        """/clear list - clears the waitlist"""
        self._waitlist.clear()
        update.message.reply_text("Waitlist cleared")

    def _clear_everything(self, update):
        self._clear_teams(update)
        self._clear_tables(update)
        self._clear_group(update)

    def _help_clear_commands(self, update):
        """help command for the clear commands"""
        help = (
            "all   -> Clears all table, teams, and waitlist\n"
            "group -> Clears master group list\n"
            "list  -> Clears the waitlist\n"
            "table -> Clears all the tables and table history\n"
            "team  -> Clears all the teams information\n"
            "help  -> Displays commands for the clear command\n"
            )
        update.message.reply_text(help)
    
    # GAMEPLAY COMMANDS
    def gameplay_commands(self, update, context):
        self._commands_get_parameters(update, "get")
        
        action = self._messages[0]
        action = action.lower()

        if "shark" in action:
            self._game_play_type = "shark"
        elif "rise" in action:
            self._game_play_type = "rise"
        elif "team" in action:
            self._game_play_type = "team"
        elif "get" in action:
            pass
        elif "help" in action:
            self._help_clear_commands(update)
        else:
            update.message.reply_text(f"ERROR:  No such subcommand {action}.  See 'play help' for more details")

        update.message.reply_text(f"Game type is {self._game_play_type}")
        return ConversationHandler.END
    
    def _help_play_commands(self, update):
        """help command for the clear commands"""
        help = (
            "get   -> Gets the current game play\n"
            "rise  -> Changes game play to rise and fly\n"
            "shark -> Changes game play to card sharks (TBD)\n"
            "team  -> Changes game play to team format (coming soon)\n"
            )
        update.message.reply_text(help)

    def quit(self, update, context):
        """/quit (ends game and prints finial results teams)"""
        active_tables = 0
        for table in self._tables:
            if table.active:
                active_tables = active_tables + 1

        if self._max_tables > 0 or active_tables > 0:
            self._max_tables = 0
            update.message.reply_text(f"Starting to close down this gaming session.  However there are {active_tables} active tables")
            self._print_tables(update=update, active_only=True)
    
        else:
            update.message.reply_text("---------- Final Results ----------")
            self._get_teams(update=update, stats=True)
            logger.warning("Game Session Ended")

            self._table_file = f"Tables_{datetime.today().strftime(self.date_query)}.txt"

            counter = 1
            while os.path.exists(self._table_file):
                self._table_file = f"Tables_{datetime.today().strftime(self.date_query)}_tourney_{counter}.txt"
                counter = counter + 1

            self._tables.clear()
            for team in self._teams:
                team.reset()
                
            msg = f"Tables cleared and team scores have been reset."
            update.message.reply_text(msg)
            
            logger.info(f"{msg} New game file is being saved to {self._table_file}.")

        return ConversationHandler.END
                
    def error_flavorful_feedback(self, update):
        """invalid command case"""
        logger.info("we get here")
        messages = ["Are we speaking the same language?!?!", "Try again mother fucker!!!", "I don't understand BS!!!", "Bruh WTF?!?!",
                    "Not today.  You ain't gonna break my shit today.", "If at first you don't succeed...Try try again!", "Ahh Sugar Honey Ice Tea!"]
        random_number = randint(0, len(messages-1))
        update.message.reply_text(messages[random_number])
        return ConversationHandler.END
        
    def main(self):
        logger.debug("starting handler")
        
        dp = self._updater.dispatcher

        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("team", self.team_commands),
                CommandHandler("table", self.table_commands),
                CommandHandler("list", self.list_commands),
                CommandHandler("clear", self.clear_commands),
                CommandHandler("print", self.print_commands),
                CommandHandler("play", self.gameplay_commands),

                # Shortcuts
                CommandHandler("add", self.add_waitlist),
                CommandHandler("next", self.next_team_to_table),
                CommandHandler("stats", self.print_stats),
                CommandHandler("help", self.help),
                CommandHandler("quit", self.quit), CommandHandler("exit", self.quit)
                ],
            states={},
            fallbacks=[CommandHandler("quit", self.quit), CommandHandler("exit", self.quit)],
        )
        dp.add_handler(conv_handler)
        dp.add_error_handler(self.error_flavorful_feedback)
        self._updater.start_polling()

        self._updater.idle()

def run_pgm():
    date = datetime.today().strftime("%Y-%m-%d")
    logger.add(f"Log_{date}_GotNextBot.txt")
    my_bot = GotNextBot(token="1150426634:AAHx71JH6IFh4yLW53gjQclhhqh5z11Bb9Y")
    my_bot.load_data()
    my_bot.main()

if __name__ == "__main__":
    run_pgm()
    