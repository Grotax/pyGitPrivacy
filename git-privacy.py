#!/usr/bin/python3
"""
git privacy
"""
import argparse
import os
import sys
import readline # pylint: disable=unused-import
import base64
import configparser
import sqlite3
import git
import progressbar
import colorama
import pandas
import timestamp
import crypto
import database

PARSER = argparse.ArgumentParser()

ARGUMENTS = {
    "hexsha": {
        "argument": "-hexsha",
        "metavar": "hexsha",
        "dest": "hexsha",
        "help": "-hexsha 7dsfg...",
        "required": False
    },
    "gitdir": {
        "argument": "-gitdir",
        "metavar": "gitdir",
        "dest": "gitdir",
        "help": "-gitdir /home/user/git/somerepo",
        "required": False
    },
    "a_date": {
        "argument": "-a_date",
        "metavar": "a_date",
        "dest": "a_date",
        "help": "-a_date ",
        "required": False
    },
    "c_date": {
        "argument": "-c_date",
        "metavar": "c_date",
        "dest": "c_date",
        "help": "-c_date ",
        "required": False
    }
}

for arg in ARGUMENTS:
    PARSER.add_argument(ARGUMENTS[arg]["argument"], metavar=ARGUMENTS[arg]["metavar"],
                        dest=ARGUMENTS[arg]["dest"], help=ARGUMENTS[arg]["help"],
                        required=ARGUMENTS[arg]["required"])

# Command Flags

PARSER.add_argument("-getstamp", help="-getstamp", action="store_true", required=False)
PARSER.add_argument("-store", help="-store", action="store_true", required=False)
PARSER.add_argument("-log", help="-log", action="store_true", required=False)
PARSER.add_argument("-clean", help="-clean", action="store_true", required=False)
PARSER.add_argument("-check", help="-check", action="store_true", required=False)
PARSER.add_argument("-anonymize", help="-anonymize", action="store_true", required=False)

ARGS = PARSER.parse_args()

def read_config(gitdir):
    """ Reads git config and returns a dictionary"""
    repo = git.Repo(gitdir)
    config = {}
    config_reader = repo.config_reader(config_level='repository')
    options = ["password", "mode", "salt", "limit", "databasepath"]
    for option in options:
        try:
            config[option] = config_reader.get_value("privacy", option)
        except configparser.NoOptionError as missing_option:
            if missing_option.option == "salt":
                print("No Salt found generating a new salt....", file=sys.stderr)
                config["salt"] = base64.urlsafe_b64encode(os.urandom(16))
                write_salt(gitdir, base64.urlsafe_b64encode(config["salt"]))
            elif missing_option.option == "mode":
                print("No mode defined using default", file=sys.stderr)
                config["mode"] = "simple"
            elif missing_option.option == "password":
                print("error no password", file=sys.stderr)
                raise missing_option
            elif missing_option.option == "limit":
                print("no limit", file=sys.stderr)
            elif missing_option.option == "databasepath":
                print("databasepath not defined using path to repository", file=sys.stderr)
                config["databasepath"] = "notdefined"
    if config["mode"] == "reduce":
        try:
            config["pattern"] = config_reader.get_value("privacy", "pattern")
        except configparser.NoOptionError as missing_option:
            print("no pattern, setting default pattern s", file=sys.stderr)
            config["pattern"] = "s"

    return config

def write_salt(gitdir, salt):
    """ Writes salt to config """
    repo = git.Repo(gitdir)
    config_writer = repo.config_writer(config_level='repository')
    config_writer.set_value("privacy", "salt", salt)
    config_writer.release()

def do_log(db_connection, repo_path):
    """ creates a git log like output """
    colorama.init(autoreset=True)

    time_manager = timestamp.TimeStamp()

    repo = git.Repo(repo_path)
    commit_list = repo.git.rev_list(repo.active_branch.name).splitlines()
    print("loaded {} commits, branch: {}".format(len(commit_list), repo.active_branch.name))

    try:
        magic_list = db_connection.get()
        for commit_id in commit_list:
            commit = repo.commit(commit_id)
            print(colorama.Fore.YELLOW +"commit {}".format(commit.hexsha))
            print("Author: {}".format(commit.author))
            if commit.hexsha in magic_list:
                real_date = magic_list[commit.hexsha]
                print(colorama.Fore.RED + "Date: {}".format(time_manager.seconds_to_gitstamp(commit.authored_date, commit.author_tz_offset)))
                print(colorama.Fore.GREEN + "RealDate: {}".format(real_date))
            else:
                print("Date: {}".format(time_manager.seconds_to_gitstamp(commit.authored_date, commit.author_tz_offset)))
            print("\t {} ".format(commit.message))
    except sqlite3.OperationalError as db_e:
        print(db_e)
        print("No data found in Database {}".format(db_connection.get_path()))

def anonymize_repo(repo_path):
    """ anonymize repo """
    time_manager = timestamp.TimeStamp(limit="16-18", pattern="h,m,s")
    repo = git.Repo(repo_path)
    commit_amount = len(repo.git.rev_list(repo.active_branch.name).splitlines())
    try:
        start_date = input("Enter the start Date [{}]:".format(time_manager.start_date()))
        if start_date == "":
            start_date = time_manager.start_date()
        try:
            start_date = time_manager.start_date(start_date)
        except ValueError:
            print("ERROR: Invalid Date")
        print("Your stardate will be: {}".format(start_date))
        datelist = pandas.date_range(start_date, periods=commit_amount).tolist()
        datelist = [time_manager.reduce(date) for date in datelist]
        datelist = [time_manager.to_string(date, git_like=True) for date in datelist]

        git_repo = git.Git(repo_path)
        progress = progressbar.bar.ProgressBar(min_value=0, max_value=commit_amount).start()
        for commit_number in range(commit_amount):
            date = datelist.pop()
            commit_hexsha = repo.git.rev_list(repo.active_branch.name).splitlines()[commit_number]

            sub_command = "if [ $GIT_COMMIT = {} ] \n then \n\t export GIT_AUTHOR_DATE=\"{}\"\n \t export GIT_COMMITTER_DATE=\"{}\"\n fi".format(commit_hexsha, date, date)
            my_command = ["git", "filter-branch", "-f", "--env-filter", sub_command]

            git_repo.execute(command=my_command)
            progress.update(commit_number)
        progress.finish()
    except KeyboardInterrupt:
        print("\n\nERROR: Cancelled by user")


def main(): # pylint: disable=too-many-branches
    """start stuff"""
    repo_path = None
    config = None
    try:
        repo_path = os.path.expanduser(ARGS.gitdir)
        config = read_config(repo_path)
    except TypeError:
        try:
            repo_path = os.getcwd()
            config = read_config(repo_path)
        except (git.InvalidGitRepositoryError) as git_error:
            print("Can't load repository: {}".format(git_error), file=sys.stderr)
            sys.exit(1)
    try:
        if config["databasepath"] != "notdefined":
            privacy = crypto.Crypto(config["salt"], str(config["password"]))
            db_connection = database.Database(config["databasepath"], privacy)
        else:
            privacy = crypto.Crypto(config["salt"], str(config["password"]))
            db_connection = database.Database(repo_path+"/history.db", privacy)
    except sqlite3.Error as sq_error:
        print("A database error occurred: {}".format(sq_error.args[0]), file=sys.stderr)
        sys.exit(1)

    time_manager = timestamp.TimeStamp(config["pattern"], config["limit"], config["mode"])
    repo = git.Repo(repo_path)

    if ARGS.getstamp:
        print(time_manager.get_next_timestamp(repo))
    elif ARGS.store:
        try:
            db_connection.put(ARGS.hexsha, ARGS.a_date, ARGS.c_date)
        except Exception as e:
            raise e
    elif ARGS.log:
        do_log(db_connection, repo_path)
    elif ARGS.clean:
        db_connection.clean_database(repo.git.rev_list(repo.active_branch.name).splitlines())
    elif ARGS.check:
        # Check for timzeone change
        repo = git.Repo(repo_path)
        commit_list = repo.git.rev_list(repo.active_branch.name).splitlines()
        commit = repo.commit(commit_list[0])
        last_stamp = time_manager.get_timezone(time_manager.seconds_to_gitstamp(commit.authored_date, commit.author_tz_offset))[1]
        next_stamp = time_manager.get_timezone(time_manager.now())[1]
        if last_stamp != next_stamp:
            print("Warning: Your timezone has changed.")
            #input("prompt")
            sys.exit(1)
    elif ARGS.anonymize:
        anonymize_repo(repo_path)
    else:
        PARSER.print_help()

    sys.exit()

if __name__ == '__main__':
    main()
