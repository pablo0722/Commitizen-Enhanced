import contextlib
import os
import tempfile

import questionary

from commitizen import factory, git, out
from commitizen.config import BaseConfig
from commitizen.cz.exceptions import CzException
from commitizen.exceptions import (
    CommitError,
    CustomError,
    DryRunExit,
    NoAnswersError,
    NoCommitBackupError,
    NotAGitProjectError,
    NothingToCommitError,
)


class Commit:
    """Show prompt for the user to create a guided commit."""

    def __init__(self, config: BaseConfig, arguments: dict):
        if not git.is_git_project():
            raise NotAGitProjectError()

        self.config: BaseConfig = config
        self.cz = factory.commiter_factory(self.config)
        self.arguments = arguments
        self.temp_file: str = os.path.join(
            tempfile.gettempdir(),
            "cz.commit{user}.backup".format(user=os.environ.get("USER", "")),
        )

    def read_backup_message(self) -> str:
        # Check the commit backup file exists
        if not os.path.isfile(self.temp_file):
            raise NoCommitBackupError()

        # Read commit message from backup
        with open(self.temp_file, "r") as f:
            return f.read().strip()

    def prompt_commit_questions(self) -> str:
        # Prompt user for the commit message
        cz = self.cz
        questions = cz.questions()
        for question in filter(lambda q: q["type"] == "list", questions):
            question["use_shortcuts"] = self.config.settings["use_shortcuts"]
        try:
            answers = {}
            for q in questions:
                if q["type"] == "multiline":
                    q["type"] = "input"
                    message = q["message"]
                    i = 1
                    q["message"] = message + " (line " + str(i) + ")"
                    a = questionary.prompt(q, style=cz.style)
                    key = list(a.keys())[0]
                    value = list(a.values())[0]
                    while list(a.values())[0] is not '':
                        i = i + 1
                        q["message"] = message + " (line " + str(i) + ")"
                        a = questionary.prompt(q, style=cz.style)
                        if list(a.values())[0] is not '':
                            value += "\n" + list(a.values())[0]
                    answer = {key: value}
                else:
                    answer = questionary.prompt(q, style=cz.style)
                answers.update(answer)
        except ValueError as err:
            root_err = err.__context__
            if isinstance(root_err, CzException):
                raise CustomError(root_err.__str__())
            raise err

        if not answers:
            raise NoAnswersError()

        return cz.message(answers)

    def __call__(self):
        dry_run: bool = self.arguments.get("dry_run")

        if git.is_staging_clean() and not dry_run:
            raise NothingToCommitError("No files added to staging!")

        force_commit: bool = False
        force_commit = self.arguments.get("force_commit")

        check_only: bool = False

        retry: bool = self.arguments.get("retry")

        if retry:
            m = self.read_backup_message()
        else:
            m = self.prompt_commit_questions()

        confirmed: bool = True
        if (m.startswith("|nonconfirmed|")):
            confirmed = False
            m = m.replace("|nonconfirmed|", "")
            check_only = True

        if(confirmed and force_commit):
            force_commit = True
        else:
            force_commit = False
            
        out.success(check_only)

        if dry_run:
            raise DryRunExit()

        signoff: bool = self.arguments.get("signoff")

        if signoff:
            co = git.commit(m, check_only, force_commit, "-s")
        else:
            co = git.commit(m, check_only, force_commit)
        c=co["c"]
        c2=co["c2"]

        out.info(c.out)
        out.error(c.err)

        if c.return_code != 0:
            # Create commit backup
            with open(self.temp_file, "w") as f:
                f.write(m)

            if check_only == False and confirmed == True:
                out.success("check has errors but try to commit anyway")
            else:
                raise CommitError()

        if c2 is not None:
            out.info(c2.out)
            out.error(c2.err)

            if c2.return_code != 0:
                # Create commit backup
                with open(self.temp_file, "w") as f:
                    f.write(m)
                raise CommitError()

        if "nothing added" in c.out or "no changes added to commit" in c.out:
            pass
        else:
            with contextlib.suppress(FileNotFoundError):
                os.remove(self.temp_file)

            out.success("Commit validation: successful!")
            
            if confirmed == True:
                out.success("Commit successful!")
            else:
                out.error("Nothing was commited (unconfirmed message)")
