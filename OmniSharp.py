import urllib, json, sublime_plugin, sublime, re, os, subprocess, threading, sys, queue
import urllib.request

omnisharp_server = "http://localhost:11000/"

# internals

# This command is needed to trigger the autocompletion when typing a dot
# E.g. myInstance.
class OmniSharpDotComplete(sublime_plugin.TextCommand):
    def run(self, edit):
        for region in self.view.sel():
            self.view.insert(edit, region.end(), ".")
        caret = self.view.sel()[0].begin()
        line = self.view.substr(sublime.Region(self.view.word(caret-1).a, caret))
        if member_regex.search(line) != None:
            self.view.run_command("hide_auto_complete")
            sublime.set_timeout(self.delayed_complete, 1)

    def delayed_complete(self):
        self.view.run_command("auto_complete")

class OmniSharpServerRunner:
    def __init__(self):
        self.stdout_queue = queue.Queue()
        self.server_proc  = None
        self.running      = False

    def is_running(self):
        return self.running == True

    def stdout_thread(self):
        try:
            while True:
                if self.server_proc.poll() != None:
                    break
                read = self.server_proc.stdout.readline().strip().decode(sys.getdefaultencoding())
                if read:
                    self.stdout_queue.put(read)
        finally:
            self.running = False
            print("OmniSharp server is no longer running.")

    def stderr_thread(self):
        try:
            while True:
                if self.server_proc.poll() != None:
                    break
                read = self.server_proc.stderr.readline().strip().decode(sys.getdefaultencoding())
                if read:
                    print("stderr: %s" % read)
        finally:
            pass

    def start(self, port, solution_file):
        cmd = ["mono"]
        cmd.append("'%s'" % (os.path.join(sublime.packages_path(), "OmniSharpSublimePlugin", "OmniSharp", "OmniSharp.exe")))
        cmd.append("-p")
        cmd.append(str(port))
        cmd.append("-s '%s'" % (solution_file))
        print('running: '+" ".join(cmd))
        self.server_proc = subprocess.Popen(
            " ".join(cmd),
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE
            )
        self.running = True
        t = threading.Thread(target=self.stdout_thread)
        t.start()
        t = threading.Thread(target=self.stderr_thread)
        t.start()

    def stop(self):
        if self.server_proc != None:
            print("Stopping OmniSharp server...")
            # kill the process if open
            try:
                self.server_proc.kill()
            except OSError:
                # can't kill a dead proc
                pass

omnisharp_server_runner = OmniSharpServerRunner()

# Command to start the server from a menu item
class OmniSharpStartServer(sublime_plugin.TextCommand):
    def run(self, edit):
        if omnisharp_server_runner.is_running():
            sublime.error_message("Already running a server OmniSharp server. You must stop it first")
            return

        self.find_solution_files()
        if len(self.solution_files) == 0 :
            sublime.error_message('No solution file found in Open Files.  Open a folder containing a .net solution')
        if len(self.solution_files) > 1 :
            messages = []
            for solution in self.solution_files:
                messages.append(["Select solution file:", solution])
            self.select_solution_file(messages)
        if len(self.solution_files) == 1 :
            self.start_server_for_solution(0)

    def find_solution_files(self):
        window  = self.view.window()
        folders = window.folders()
        self.solution_files = []
        if len(folders) == 1:
            active_folder = folders[0]
            for r,d,f in os.walk(active_folder):
                for files in f:
                    if files.endswith(".sln"):
                        self.solution_files.append(os.path.join(r,files))

    def select_solution_file(self, messages):
        window = self.view.window()
        window.show_quick_panel(messages, self.start_server_for_solution)

    def start_server_for_solution(self, selected_index):
        if 0 <= selected_index and len(self.solution_files) > selected_index:
            solution_file = self.solution_files[selected_index]
            omnisharp_server_runner.start(11000, solution_file)

# Command to stop the server from a menu item
class OmniSharpStopServer(sublime_plugin.TextCommand):
    def run(self,edit):
        omnisharp_server_runner.stop()

# Also stop server when unloading
def plugin_unloaded():
    omnisharp_server_runner.stop()

# Updates and build the completion list / checks for syntax errors
class OmniSharp(sublime_plugin.EventListener):
    word_list = []

    def on_close(self, view):
        windows = sublime.windows()
        if(len(windows) <= 0):
            omnisharp_server_runner.stop()
        elif(len(windows) == 1):
            views = windows[0].views()
            if(len(views) <= 0):
                omnisharp_server_runner.stop()

    def on_pre_save(self, view):
      self.view = view
      # TODO write error to line (see SublimeLinter)
      if self.is_dotnet_file(view.scope_name(view.sel()[0].begin())):
          js = self.get_response('/syntaxerrors')
          if 'Errors' in js:
            self.show_errors(view, js)

    def show_errors(self, view, data):
        if len(data['Errors']) > 0:
          view.set_status('message', 'Syntax errors.  View the console for details')
          print(data['Errors'])
        else:
          view.set_status('message', '')

    def load_completions(self, view):
        scope_name = view.scope_name(view.sel()[0].begin())
        if self.is_dotnet_file(scope_name):
            parameters = {}
            location = self.view.sel()[0]
            word     = self.view.substr(self.view.word(location.a))
            cleaned_word = word_regex.sub('', word).strip(whitespace)
            # reject ".", OmniSharp handles this case very well
            cleaned_word = "" if cleaned_word == "." else cleaned_word
            parameters['wordToComplete'] = cleaned_word
            completions = self.get_response('/autocomplete', parameters)

            self.word_list[:] = []
            for completion in completions:
                self.append_completion_entries(completion)

    def append_completion_entries(self, completion):
        word = completion['CompletionText']
        desc = completion['DisplayText']
        full = ""
        if word.endswith('(') or word.endswith(')'): #methods
            full = completion['Description'].replace(desc, "", 1).strip(whitespace).lstrip(method_strip)
            # truncate as sublime still has problems with long completion texts
            full = (full[:100]) if len(full) > 100 else full
        else: # all others (e.g. properties, classes, ...)
            desc += "\t"+completion['Description'].strip(whitespace)

        self.word_list.append((desc, self.argument_brackets(word)))
        # add a second line with same substitution but a full description
        if full != "":
            self.word_list.append(("  "+full, word))

    def argument_brackets(self, word):
        # insert matching brackets
        if word.endswith('('):
            word += "$1)$2"
        elif word.endswith('<'):
            word += "$1>($2)"
        return word

    def is_dotnet_file(self, scope):
        return ".cs" in scope

    def get_autocomplete_list(self, view, word):
        self.load_completions(view)
        autocomplete_list = self.word_list
        return (autocomplete_list, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)

    # gets called when auto-completion pops up.
    def on_query_completions(self, view, prefix, locations):
        if self.is_dotnet_file(view.scope_name(view.sel()[0].begin())):
            self.view = view
            return self.get_autocomplete_list(view, prefix)

    def on_query_context(self, view, key, operator, operand, match_all):
        if key == "omnisharp.dotcomplete":
            return True
        elif key == "omnisharp.supported_language":
            result = self.is_dotnet_file(view.scope_name(view.sel()[0].begin()))
            return result
        elif key == "completion_common.is_code":
            caret  = view.sel()[0].a
            scope  = view.scope_name(caret).strip()
            result = re.search("(string.)|(comment.)", scope) == None
            return result

    def get_response(self, endpoint, additionalParameters=None):
        parameters = {}
        location = self.view.sel()[0]
        cursor   = self.view.rowcol(location.begin())
        parameters['line']     = cursor[0] + 1
        parameters['column']   = cursor[1] + 1
        parameters['buffer']   = self.view.substr(sublime.Region(0, self.view.size()))
        parameters['filename'] = self.view.file_name()

        if additionalParameters != None:
          parameters.update(additionalParameters)

        target     = urllib.parse.urljoin(omnisharp_server, endpoint)
        parameters = urllib.parse.urlencode(parameters)
        parameters = parameters.encode('utf-8')
        try:
            response = urllib.request.urlopen(target, parameters)
        except urllib.error.URLError:
            return {}

        js = response.read().decode("utf8")

        if(js != ''):
            return json.loads(js)

member_regex = re.compile("(([a-zA-Z_]+[0-9_]*)|([\)\]])+)(\.)$")
word_regex   = re.compile("'[\.\)]")
whitespace   = " \t\n\r"
method_strip = ";\s+"
