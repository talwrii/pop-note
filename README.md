# pop-note
A single editable note that you can pop up and hide with a keybinding. Requires X11 (normally used with linux) (easy fix tho)

Unreviewed ai-generated code.

## Motivation
I don't have any window space and my computer only accepts two monitors. I don't want to change anything about my editor, or note taking app.

Philosophy, don't separate process and capture.

## Alternatives
So many alternatives:

* Buy a monitor or a new computer and put it somewhere. Monitors are basically free nowerdays.
* Put your notes on another desktop and toggle desktops. Get it to launch at start up
* Have a shortcut to raise you editor / editor window (run-or-raise)
* Using something capture based like org mode, where you capture the information and process it latter
* Go to your daily not in obsidan and use the back button

But for now I just want this and I am feeling lazy.

This was kind of influenced by "quake style pop-down" terminals. But I am too lazy to implement a pop-down syle animation.

## Feature requests
No.

This is one of thos apps which is designed to have no features. If you want somethign clever, use one of the approaches above. 

I might however add the features I want.


## Caveats
Only works with x11 because tkinter window raising does not work reliably with KDE so I had to use wmctrl to raise windows. Apparently there are different tools for every wayland compositor so if you use one of those you could special case this and send it to me.

## Installation
```
pipx install pop-note
```
Make sure `wmctrl` and you are using `X11`. If you are not using X11 you can likely edit the wmctrl to something specific to your window manager.

## Usage
`pop-note` will pop up the note and hide it. I have a keyboard shortcut in KDE for this. 

## About me
I am @readwith. If you are interested in note-taking [read this](https://readwithai.substack.com/p/note-taking-with-obsidian-much-of)
