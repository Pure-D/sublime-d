# sublime-d

D extension for sublime text using workspace-d

Currently implemented:
* Auto completion for dub projects & plain projects
* Documentation lookup by hovering over symbols
* Calltips
* Go To Definition (Ctrl-Shift-P -> Go To Definition)
* Outlining the Document (Ctrl-Shift-O / Ctrl-Shift-P -> Outline Document)
* Formatting the Document (Shift-Alt-F / Ctrl-Shift-P -> Format Code)

Currently folder detection / plugin startup is very hacky and might not work with multiple instances of sublime text. The plugin might also require a manual startup by saving the SublimeD.py and quickly clicking into the sublime window with the project.