from subprocess import *
from print_colors import colors as col
import os
import re
from glob import glob
import platform
import zipfile
from collections import namedtuple

# PATH CONSTANTS
TESTS_PATH = "tests"
TEST_TEMPLATES_PATH = "test_templates"
ASSIGNMENTS_PATH = "assignments"

# FIELDS
test_templates = {}     # Stores the prolog query templates that are used in the tests
tests = {}              # Keys: Folder name where the test resides, Values: a Test instance (see class Test)
assignments = {}        # Keys: Group names, extracted from group folders, Values: Concatenated knowledge of prolog files
shell_command = []      # Stores the shell command to be used, depends on system (only Windows supported for now)

# CLASSES
class TestCase:
    result = ''
    success = "unknown"

    def __init__(self, name, type, goal, expected):
        self.name = name
        self.type = type
        self.goal = goal
        self.expected = expected

    def reset(self):
        self.result = ''
        self.success = "unknown"

    def __str__(self):
        return f"TestCase(name={self.name}, type={self.type}, goal={self.goal}, expected={self.expected}, " \
               f"result={self.result} success={self.success})"

    def __repr__(self):
        return self.__str__()


class Test:
    def __init__(self, test_groups=None, pre="", abolish=None, database=""):
        if test_groups is None:
            test_groups = {}
        if abolish is None:
            abolish = []
        self.pre = pre
        self.abolish = abolish
        self.database = database
        self.test_groups = test_groups

    def reset(self):
        for test_group in self.test_groups:
            for test_case in self.test_groups[test_group]:
                test_case.reset()

    def __str__(self):
        return f"Test(test_cases={str(self.test_groups)}, pre={self.pre}, abolish={self.abolish}, database={self.database})"

    def __repr__(self):
        return self.__str__()


# MAIN
def main():
    # Initialize resources
    init_shell()
    init_test_templates()
    init_tests()
    init_assignments()

    # Iterate over the group names
    for group_name in assignments:
        print(f"Processing group {group_name}")

        # Write the knowledge for this group to the working directory so that we may use it in the commandline calls
        with open("knowledge.temp", "w") as file:
            file.write(assignments[group_name].knowledge)

        # Sanity check for knowledge to skip it (in case of syntax errors)
        cmd = ['swipl -G1m -q -g consult("knowledge.temp") -t halt']
        out = command_call(shell_command, cmd)
        if "ERROR" in out[1]:
            print(col.WARNING, f"Knowledge of group {group_name} contains errors, skipping test run..", col.ENDC)
            continue

        # Clear any previous test output files in the group's assignment folder if present
        for f in glob(f"{assignments[group_name].assignment_path}{os.sep}*.out"):
            try:
                os.remove(f)
            except FileNotFoundError:
                pass

        # Run the tests
        for exercise in tests:
            print(f"Running tests for exercise {exercise}")
            # Write pre-knowledge and database to working directory
            with open("pre.temp", "w") as file:
                file.write(tests[exercise].pre)
            with open("database.temp", "w") as file:
                file.write(tests[exercise].database)

            # Reset all tests for every group/exercise
            tests[exercise].reset()
            process_hand_in(group_name, exercise, tests[exercise])

    # Clean up any temporary files in the working directory
    clean_up()

    print("Finished running all tests on all assignments!")


# Remove all left-over files
def clean_up():
    # Cleaning up temporary files created in the process
    for t in glob("*.temp"):
        try:
            os.remove(t)
        except FileNotFoundError:
            pass


# Assign the proper shell command according to the OS
def init_shell():
    global shell_command

    # Identify the shell we're running on (just informative for now)
    try:
        print("Current shell:", os.environ['SHELL'])
    except KeyError:
        print("Not running from shell currently")

    # Assign the shell command
    # TODO: implement bash support and possibly support for other shells where SWI-Prolog can be used
    if platform.system() == 'Windows':
        print("Using cmd as shell...")
        shell_command = [r'cmd', r'/C']
    else:
        print("No available and supported shell found!")
        exit(1)


# Initialize the test template files
def init_test_templates():
    global test_templates

    # Reads and stores template files according to name
    for ttn in [q.split("\\")[1] for q in glob(f"{TEST_TEMPLATES_PATH}{os.sep}*")]:
        with open(os.path.join(TEST_TEMPLATES_PATH, ttn), "r") as file:
            test_templates[ttn] = file.read()


# Read a test file containing test cases, constructing a Test instance
# TODO: Too long and complicated, requires refactor
def read_test_file(file_name):
    with open(file_name, "r") as file:
        test_group = ""
        test_groups = {}
        in_group = False

        # Go through the lines in the test file, while keeping track of whether we're in an optional group or not
        for test_line in file.readlines():
            # Reset the test group name if we're not in one anymore
            if not in_group:
                test_group = ""
            # Comments are ignored
            if test_line.startswith("#") or test_line.strip() == "":
                continue
            # Starting delimiter for optional groups
            if test_line.startswith("GROUP"):
                test_group = test_line.split(":")[1].strip()
                in_group = True
                continue
            # Ending delimiter for optional groups
            if test_line.startswith("--"):
                test_group = ""
                in_group = False
                continue

            # Split test case line on tabs, strip all remaining spaces, while ignoring empty strings resulting from that
            split_test = [x.strip() for x in re.split(r"\t", test_line.strip()) if x.strip() != '']

            # The first entry is the name, and the third entry is the type of test template to use
            name = split_test[0].strip()
            type = split_test[2].strip()

            # If we're not in a test group, then the test group name trivially becomes the test's name
            if not test_group:
                test_group = name

            # Do not allow duplicate test case names
            if name in map(lambda x: x.name, flatten(test_groups.values())):
                print(col.FAIL, f"ERROR: Duplicate test names in {file_name}, please fix this!", col.ENDC)
                exit(1)

            # Will store a test goal and its test variables
            Goal = namedtuple("Goal", ['goal', 'vars'])

            # Process the goal string (second entry), and deal with the test variables
            goal_str = split_test[1].strip()
            vars = re.findall(r"<TVAR:[A-Z]\w*>", goal_str)
            var_list = []
            # Extract test variable name, replace it in the goal and append it to the variable list
            for var_raw in vars:
                var = var_raw[var_raw.find(":") + 1:var_raw.find(">")]
                goal_str = goal_str.replace(var_raw, var)
                var_list.append(var)
            goal = Goal(goal_str, var_list)

            # Process expected output:
            # It is formatted as: <VAR1>=<RESULT1>|:|<VAR2>=<RESULT2>|:|<VAR3>=<RESULT3>|:|.... etc
            expected_list = [x.strip() for x in split_test[3].strip().split("|:|") if len(x.strip()) > 0]
            expected = dict(map(lambda x: (x[:x.find("=")], x[x.find("=") + 1:]), expected_list))


            # Some more checks to make sure the expected results are sane in terms of variables used
            for var in expected:
                if not var[0].isupper():
                    print(col.FAIL,
                          f"Variable {var} in test {name} should start with uppercase character, aborting",
                          col.ENDC)
                    exit(1)
                # The "Result" variable is special and is used to output other meaningful data from certain queries
                if var not in var_list and var != "Result":
                    print(col.FAIL, f"ERROR: variable {var} is not present in goal for test {name}, aborting",
                          col.ENDC)
                    exit(1)

            # Construct test case instance
            test_case = TestCase(name, type, goal, expected)

            # Put it in a test group if the group already exists, otherwise put it in a new one
            if test_group:
                if test_group in test_groups:
                    test_groups[test_group].append(test_case)
                else:
                    test_groups[test_group] = [test_case]

        return test_groups


# Initialize all the tests
def init_tests():
    global tests

    # Iterate through the folders in "tests" folder
    for folder_name in map(os.path.basename, glob(f"{TESTS_PATH}{os.sep}*")):
        # Skip if folder starts with "_" or if it's not a folder at all
        if folder_name.startswith("_") or not os.path.isdir(folder_name):
            continue

        test_path = f"{TESTS_PATH}{os.sep}{folder_name}{os.sep}"

        # If it really contains a file with tests...
        if os.path.isfile(test_path + "tests.txt"):
            # Read the tests
            test = Test(read_test_file(test_path + "tests.txt",))

            # If present, read the file that contains the predicates to abolish (comma separated)
            if os.path.isfile(test_path + "abolish.txt"):
                with open(test_path + "abolish.txt", "r", errors='ignore') as file:
                    test.abolish = [x.strip() for x in file.read().split(",")]

            # If present, read the file that contains the pre-knowledge (consulted before anything else)
            if os.path.isfile(test_path + "pre.pl"):
                with open(test_path + "pre.pl", "r", errors='ignore') as file:
                    test.pre = file.read()

            # If present, read the file that contains a custom database for the test (consulted after abolishing)
            if os.path.isfile(test_path + "database.pl"):
                with open(test_path + "database.pl", "r", errors='ignore') as file:
                    test.database = file.read()

            tests[folder_name] = test


# Strip all types of comments to avoid some typos people make...
# Also gets rid of some unsupported commenting format causing operator errors
def remove_stupidity(text):
    text = re.sub(re.compile('^%.*', re.MULTILINE), "", text)
    text = re.sub(re.compile('^//.*', re.MULTILINE), "", text)
    text = re.sub(re.compile('^/\*.*\*/', re.MULTILINE), "", text)
    text = re.sub(re.compile('^/.*/', re.MULTILINE), "", text)
    return text


# Extracts group name from blackboard style group names
def get_group_name_blackboard(assignment_directory_name):
    start_index = assignment_directory_name.find("Group")
    end_index = assignment_directory_name.find("_", start_index)
    return assignment_directory_name[start_index:end_index].replace(" ", "_").lower()


# Extracts group name from brightspace style group names
def get_group_name_brightspace(assignment_directory_name):
    splt = assignment_directory_name.split("-")
    if len(splt) > 3:
        return f"{splt[2].strip()}_{splt[3].strip()}"
    return "INVALID_FOLDER_NAME"

# Unzips a zip file to the same folder it is in, then deletes it if possible
def unzip(zip_path):
    zip_ref = zipfile.ZipFile(zip_path, 'r')
    zip_dir, _ = os.path.split(zip_path)
    zip_ref.extractall(zip_dir)
    zip_ref.close()
    try:
        os.remove(zip_path)
    except:
        print(col.FAIL, "ERROR: Could not remove zip file!", col.ENDC)
        exit(1)


# Recursively traverses the directory structure to find where the prolog files are located
# It also unzips any .zip files it finds, and removes it when unzipped
def get_prolog_files(directory_path):
    files = []

    for path in glob(directory_path + "\\*"):
        if os.path.splitext(path)[-1] in [".zip"]:
            unzip(path)
            files += get_prolog_files(directory_path)
        if os.path.splitext(path)[-1] in [".pl", ".pro"]:
            files.append(path)
        if os.path.isdir(path):
            files += get_prolog_files(path)
    return files


# Load all assignment prolog files from all groups
def init_assignments():
    global assignments

    # Get all submission folder paths
    assignment_directories = glob(f"{ASSIGNMENTS_PATH}{os.sep}*")
    Assignment = namedtuple("Assignment", ["assignment_path", "knowledge"])

    # Iterate over them..
    for assignment_path in assignment_directories:
        # Ignore if not a directory
        if not os.path.isdir(assignment_path):
            continue

        # Get the group name
        group_name = get_group_name_brightspace(assignment_path)

        # Create knowledge file, concatenated from all prolog files found in the submission folder
        knowledge = ""
        for file_path in get_prolog_files(assignment_path):
            with open(file_path, "r", errors='ignore') as file:
                knowledge += file.read() + "\n"

        # If no knowledge was added, skip the group, since there's nothing to test
        if knowledge == "":
            print(col.WARNING, f"Group {group_name} has no prolog files that can be tested...", col.ENDC)
            continue

        assignments[group_name] = Assignment(assignment_path, remove_stupidity(knowledge))


# Construct an appropriate command string from a list of commands
def to_cmd_string(cmd_list):
    cmd = ""
    for s in cmd_list:
        cmd += s + " & "
    return cmd[:-3]


# Call a command given shell and obtain output and errors. Kill process after that.
# TODO: Could vastly speed things up if prolog would be kept alive instead
def command_call(shell, command):
    shell = shell[:] + [to_cmd_string(command)]
    p = Popen(shell, stdout=PIPE, stderr=PIPE, shell=True)
    output, error = p.communicate()
    p.kill()
    # Ignore decoding errors to prevent any stalls
    return output.decode("utf-8", errors='ignore'), error.decode("utf-8", errors='ignore')


# Flatten a list containing lists
def flatten(l):
    return [item for sublist in l for item in sublist]


# Turns a test case into a test query that is runnable by prolog, and generates meaningful output
# <GOAL> will be replace by the test goal
# <EXPECTED> will be replaced by the expected values for the variables
# <WRITEVAR> will be replaced by some code that will output the value of the variable, separated by delimiters
def construct_test_query(test_case):
    template = test_templates[test_case.type]

    # Construct goal
    template = template.replace("<GOAL>", test_case.goal.goal)

    # Construct unification test(s)
    uni = []
    write = [test_case.goal.goal]
    for var in test_case.expected:
        uni.append(f"{var}={test_case.expected[var]}")
        write.append(f'write("{var}"),write("="),write({var}),write("|:|")')
    template = template.replace("<EXPECTED>", ",".join(uni))
    template = template.replace("<WRITEVAR>", ",".join(write))
    return template


# Creates a test file that prolog can run, consisting of a single test
def make_single_test_file(test_case):
    if test_case.type not in test_templates:
        return False
    with open(test_case.type + ".temp", "w") as out_file:
        out_file.write("go :- " + construct_test_query(test_case) + ".")
    return True


# Creates a test file that prolog can run, consisting of all test cases in a test, magically fused together
def make_composed_test_file(test_cases):
    test_str = "go :- "
    for test_case in test_cases:
        if test_case.type not in test_templates:
            print(col.FAIL, f"Test file creation failed, unknown test_case type {test_case.type}", col.ENDC)
            return False
        pl_code = construct_test_query(test_case)
        pl_code = pl_code.replace("writeln(pass)", "write(pass),writeln('||||')")
        pl_code = pl_code.replace("writeln(fail)", "write(fail),writeln('||||')")

        # This regex is very magical, it basically captures prolog variables without stuff that is not a prolog variable
        # It's necessary to do this replacement, to allow unique variable names between the test cases
        pl_code = re.sub(r'\b([A-Z](\w)*)\b(?=(?:[^\"]|\"[^\"]*\")*$)(?=(?:[^\']|\'[^\']*\')*$)',
                         r'\1' + "_" + test_case.name.upper(), pl_code)
        test_str += "(" + pl_code + "),"

    with open("composed.temp", "w") as out_file:
        out_file.write(test_str[:-1] + ".")
    return True


# Constructs the goal to use in the commandline for swi-prolog
def construct_test_goal(test_type, abolish_list, pre_processing, database):
    goal = ""

    if pre_processing:
        goal += 'consult("pre.temp"),'
    goal += 'consult("knowledge.temp"),'
    if abolish_list:
        for predicate in abolish_list:
            goal += f"abolish({predicate}),"
    if database:
        goal += 'consult("database.temp"),'
    goal += f'consult("{test_type}.temp"),'
    goal += "go."
    return goal


# TODO: Factor out the common parts between the two test running methods

# Run a single test, returns True if test succeeds, False otherwise
def run_test(test, test_case):
    if not make_single_test_file(test_case):
        print(col.FAIL, f"  Test file creation failed for test {test_case.name}, check tests file", col.ENDC)
        test_case.result = "ERROR, test file creation failed, check tests file"
        return False

    # Construct goal
    goal = construct_test_goal(test_case.type, test.abolish, test.pre, test.database)
    # -G128k: set global stack to 128kb to make it crash early on infinite loops
    # -q: set mode on quiet, no meaningless output
    # -g: Run goal after this token
    # -t: Run what comes after this token at the end (in this case, halt)
    cmd = ['swipl -G128k -q -g' + " " + goal + f" -t halt"]
    out = command_call(shell_command, cmd)

    # If there's an error, put that in the result field instead
    if out[1].count("ERROR:") > 0:
        print(f"  Test {test_case.name} produced an error in SWI-Prolog:")
        error_message = ""
        for line in out[1].split("\n"):
            if "ERROR" in line:
                error_message += line.strip() + " "
                print(col.FAIL + "  \t" + line + col.ENDC)
        test_case.result = [f"Prolog error report: {error_message}"]
        test_case.success = "fail"
        return False

    # The results for the test variables are always separated by |:|
    output = out[0].strip().split("|:|")
    test_case.result = [x.strip() for x in output[:-1]]

    # Final token tells whether the test passed or failed
    test_case.success = output[-1].strip()

    return True


# Run a composed test, returns True if test succeeds, False otherwise
def run_composed_test(test):
    test_cases = flatten(test.test_groups.values())
    if not make_composed_test_file(test_cases):
        return False

    # Construct goal
    goal = construct_test_goal("composed", test.abolish, test.pre, test.database)
    # -G128k: set global stack to 128kb to make it crash early on infinite loops
    # -q: set mode on quiet, no meaningless output
    # -g: Run goal after this token
    # -t: Run what comes after this token at the end (in this case, halt)
    cmd = ['swipl -G128k -q -g' + " " + goal + f" -t halt"]
    out = command_call(shell_command, cmd)
    results = out[0].split("||||")[
              :-1]  # This sequence is always present at the end, so last split entry always empty

    # If there's an error, print it and return False
    if out[1].count("ERROR:") > 0:
        print(f"Composed test produced an error in SWI-Prolog:")
        for line in out[1].split("\n"):
            if "ERROR" in line:
                print(col.FAIL + "\t" + line + col.ENDC)
        return False

    # In some odd cases, there may be a number of results different from the number of test cases
    # In such a case the test should fail, as its output is meaningless and crash-prone
    if len(test_cases) != len(results):
        return False

    # Process the results for each test case
    count = 0
    for result in results:
        # The results for the test variables are always separated by |:|
        output = result.strip().split("|:|")
        test_cases[count].result = [x.strip() for x in output[:-1]]

        # Final token tells whether the test passed or failed
        test_cases[count].success = output[-1].strip()
        count += 1

    return True


# Runs a test, and creates the output files
def process_hand_in(group_name, exercise, test):

    # Run tests
    # If the composed test fails its run...
    if not run_composed_test(test):
        print(f"Composed test for exercise {exercise} failed for group {group_name}, running single tests instead...")

        # Run the test groups individually (single tests have their own group)
        for test_group in test.test_groups:
            for test_case in test.test_groups[test_group]:
                if run_test(test, test_case):
                    print(f"  Test {test_case.name} for exercise {exercise} executed successfully!")
                else:
                    print(f"  Test {test_case.name} for exercise {exercise} failed!")
    else:
        print(f"Composed test for exercise {exercise} executed successfully for group {group_name}")

    # Determine whether all test_cases succeeded or not
    correct = "+"
    scores = {}
    for test_group in test.test_groups:
        test_cases_group = test.test_groups[test_group]
        score = sum([1 for x in test_cases_group if x.success == "pass"])
        if score == 0:
            correct = "-"
        scores[test_group] = score

    # Write output file
    # TODO: Split this off so that the table can be constructed for columns of arbitrary size
    # TODO: Make output more readable (especially test groups vs tests)
    with open(os.path.join(assignments[group_name].assignment_path, f"{correct}{exercise}.out"), "w") as file:
        file.write("{0:<40}{1:<60}{2:<15}{3:<15}{4:<80}{5:<80}"
                   .format("Name:", "Goal:", "Type:", "Pass/Fail:",  "Expected:", "Result:") + "\n")
        file.write("=" * 250 + "\n")
        for test_group in test.test_groups:
            test_cases_group = test.test_groups[test_group]
            spaces = ""
            # If we're dealing with a non-trivial test group, use a different format
            if len(test_cases_group) > 1:
                spaces = "  "
                a = lambda x: "pass" if (x > 0) else "fail"
                file.write("\n")
                file.write("-" * 250 + "\n")
                file.write(f"{'OPTIONAL GROUP: ' + test_group:<115}{a(scores[test_group])}\n")
                file.write("-"*250+"\n")
            for test_case in test_cases_group:
                file.write(
                    f"{spaces + test_case.name:<40}"
                    f"{test_case.goal.goal:<60}"
                    f"{test_case.type:<15}"
                    f"{test_case.success:<15}"
                    f"{','.join(map(lambda x: x+'='+test_case.expected[x], test_case.expected)):<80}"
                    f"{', '.join(test_case.result):<80}" + "\n"
                )
            if len(test_cases_group) > 1:
                file.write("\n")

# :D
main()
