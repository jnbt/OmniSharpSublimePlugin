import urllib, json, sublime_plugin, sublime, re
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

# Updates and build the completion list / checks for syntax errors
class OmniSharp(sublime_plugin.EventListener):
    word_list = []

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
