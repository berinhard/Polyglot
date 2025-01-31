from __future__ import absolute_import, print_function

from ..network.message import *

from ..config import *
from ..utils import *
from ..interpreter import *

from .peer import Peer, rgb2hex, hex2rgb
from .bracket import BracketHandler
from .menu_bar import MenuBar, PopupMenu
from .textbuffer import BufferTab
from .drag import VerticalDragbar
from .status_bar import StatusBar

from .tkimport import Tk, tkFont

import os, os.path
import time
import sys
import webbrowser

try:
    
    import queue

except ImportError:
    
    import Queue as queue

ROOT = None

def get_root_gui():
    global ROOT
    if not ROOT:
        ROOT = Tk.Tk()
    return ROOT

class BasicInterface:
    """ Class for displaying basic text input data.
    """
    def __init__(self):
        self.root = get_root_gui()
        self.root.configure(background=COLOURS["Background"])
        self.root.resizable(True, True)

        self.wait_msg = None
        self.waiting  = None
        self.msg_id   = 0

        # Store information about the last key pressed
        self.last_keypress  = ""
        self.last_row       = 0
        self.last_col       = 0

        self._debug_queue = []

    def run(self):
        """ Starts the Tkinter loop and exits cleanly if interrupted"""
        # Continually check for messages to be sent
        self.client.update_send()
        self.client.input.mainloop()
        return

    def kill(self):
        """ Terminates cleanly """
        self.root.destroy()
        return

    def reset_title(self):
        """ Overloaded in Interface class """
        return

class Interface(BasicInterface):
    def __init__(self, client, title, lang_data, logging=False):

        # Inherit

        BasicInterface.__init__(self)

        # Reference to client information

        self.client = client
        self.peers  = self.client.peers
        self.peer_tags  = []
        self.local_peer = None

        # Queue for reading messages

        self.queue = queue.Queue()

        # Define message handlers

        self.handles = {}

        self.add_ignore_handle() # For other messages

        self.add_handle(MSG_CONNECT,            self.handle_connect)
        self.add_handle(MSG_OPERATION,          self.handle_operation)
        self.add_handle(MSG_SET_MARK,           self.handle_set_mark)
        self.add_handle(MSG_SELECT,             self.handle_select)
        self.add_handle(MSG_EVALUATE_BLOCK,     self.handle_evaluate)
        self.add_handle(MSG_EVALUATE_STRING,    self.handle_evaluate_str)
        self.add_handle(MSG_REMOVE,             self.handle_remove)
        self.add_handle(MSG_KILL,               self.handle_kill)
        self.add_handle(MSG_SET_ALL,            self.handle_set_all)
        self.add_handle(MSG_RESET,              self.handle_soft_reset)
        self.add_handle(MSG_REQUEST_ACK,        self.handle_request_ack)
        self.add_handle(MSG_CONSOLE,            self.handle_console_message)
        self.add_handle(MSG_LANG_LEADER,        self.handle_update_lang_leader)

        # Set title and configure the interface grid

        self.title = title

        self.root.title(self.title)

        self.root.update_idletasks()

        self.center()

        self.root.protocol("WM_DELETE_WINDOW", self.client.kill )

        # Track whether user wants transparent background

        self.transparent = Tk.BooleanVar()
        self.transparent.set(False)
        self.using_alpha = (SYSTEM != WINDOWS)

        self.configure_font()

        # Dict of ID to Interpreter

        self.lang_data = lang_data

        # Menubar

        self.menu = MenuBar(self, visible = True)

        # Right-click menu

        self.popup = PopupMenu(self)

        # Set up Buffers

        self.buffer_frame = Tk.Frame(self.root, bg=COLOURS["Background"])
        self.buffer_frame.grid(row=0, column=0, sticky=Tk.NSEW)

        self.status_bar = StatusBar(self, height=25, bg="Gray", padx=10, pady=5)
        self.status_bar.grid(row=1, column=0, sticky=Tk.NSEW)

        self.root.rowconfigure(0, weight=1) # buffer frame
        self.root.rowconfigure(1, weight=0) # Status bar
        self.root.columnconfigure(0, weight=1) 
        self.buffer_frame.rowconfigure(0, weight=1) # Make sure buffer tabs expand

        self.buffers = {}

        for i, lang_info in self.lang_data.items():

            # Tuple of interpreter and EspGrid sync info

            lang, sync = lang_info

            self.add_new_buffer(i, lang, sync)

        self.block_messages = False # flag to stop sending messages

        # Set the window focus

        # Could get the id for language selected? *TODO*

        start_id = 0

        self.buffers[start_id].text.focus_force()

        self.buffer_frame.grid_propagate(False)
        self.root.update_idletasks()

        def set_widths():

            widths=[]

            for i, buf in self.buffers.items():

                widths.append(buf.winfo_width())

                self.buffer_frame.columnconfigure(i*2, weight=0)

                buf.config(width=widths[i])

            # Redraw peer labels to fit

            for _, peer in self.peers.items():
                
                peer.redraw()

            return

        self.root.after(200, set_widths)

        # Begin listening for messages

        self.listen()

    # Top-level handling
    # ==================

    def add_ignore_handle(self):
        """ Adds a handler for ignoring messages """
        self.handles[-1] = lambda *args: None
        return

    def add_handle(self, msg_cls, func):
        """ Associates a received message class with a method or function """
        self.handles[msg_cls.type] = func
        return

    def handle(self, message):
        ''' Passes the message onto the correct handler '''
        # return self.handles[message.type](message)
        return self.handles.get(message.type, -1)(message)

    # Main loop actions
    # =================

    def put(self, message):
        """ Checks if a message from a new user then writes a network message to the queue """
        
        assert isinstance(message, MESSAGE)
        
        self.queue.put(message)
        
        return

    # Updating the buffer-frame
    # =========================

    def add_new_buffer(self, lang_id, lang, sync=True):
        """ Creates a text buffer and activates the language interpreter """
        col = (len(self.buffers) * 2)

        self.buffers[lang_id] = BufferTab(self, lang_id, lang(), sync_to_espgrid=sync)
        self.buffers[lang_id].grid(row=0, column=col, sticky=Tk.NSEW)

        if col > 0: # only works with langs in serial
        
            dragbar1 = VerticalDragbar(self, self.buffers[lang_id - 1], self.buffers[lang_id], bg="Gray", width=2)
            dragbar1.grid(row=0, column=col - 1, sticky=Tk.NSEW)

        self.buffer_frame.columnconfigure(col, weight=1)
        self.buffers[lang_id].grid_propagate(False)
        
        return

    # Handle methods
    # ==============

    def handle_connect(self, message):
        ''' Prints to the console that new user has connected '''
        if self.local_peer.id != message['src_id']:

            # If a user has connected before, use that Peer instance

            if message["src_id"] in self.peers:

                self.reconnect_user(message['src_id'], message['name'])

            else:

                self.add_new_user(message['src_id'], message['name'])

            # print("Peer '{}' has joined the session".format(message['name'])) # Maybe add a popup?

        return

    def handle_request_ack(self, message):
        """ After a new client connects, respond to the server to acknowledge"""
        if message['flag'] == 1:
            self.block_messages = True
            self.add_to_send_queue(MSG_CONNECT_ACK(self.local_peer.id))
        elif message['flag'] == 0:
            self.block_messages = False
        return

    def handle_kill(self, message):
        ''' Cleanly terminates the session '''
        return self.freeze_kill(message['string'])

    def handle_remove(self, message):
        """ Removes a Peer from the session based on the contents of message """
        peer = self.get_peer(message)
        print("Peer '{!s}' has disconnected".format(peer))
        peer.remove()
        return

    def handle_set_all(self, message):
        ''' Sets the contents of the text box and updates the location of peer markers '''
        
        for buf_id, documents in message["buffers"].items():
        
            self.buffers[int(buf_id)].text.handle_set_all(*documents)
        
        for peer_id, location in message["peers"].items():

            peer_id = int(peer_id)

            if peer_id in self.peers:
               
                self.peers[peer_id].move(*location)
        
        return

    # Handle forwards

    def handle_operation(self, message):
        self.buffers[message["buf_id"]].text.handle_operation(message)
        return

    def handle_set_mark(self, message):
        self.buffers[message["buf_id"]].text.handle_set_mark(message)
        return

    def handle_select(self, message):
        """ Update's a peer's selection """
        self.buffers[message["buf_id"]].text.handle_select(message)
        return

    def handle_evaluate(self, message):
        """ Highlights text based on message contents and evaluates the string found """
        self.buffers[message["buf_id"]].text.handle_evaluate(message)
        return

    def handle_evaluate_str(self, message):
        """ Evaluates a string as code """
        self.buffers[message["buf_id"]].text.handle_evaluate_str(message)
        return

    def handle_soft_reset(self, message):
        """ Sets the revision number to 0 and sets the document contents """
        for i, buf in self.buffers.items():

            buf.soft_reset()

        self.handle_set_all(message)
        
        return

    def handle_console_message(self, message):
        """ Prints a console message received from another user """
        self.buffers[message['buf_id']].text.handle_console_message(message)
        return

    def handle_update_lang_leader(self, message):
        """ Tells the local peer to be a language leader for languages that 
            it is the only active user of """
            
        self.local_peer.update_lang_leader_info(message['flags'])

        return

    # def handle_text_constraint(self, message):
    #     """ A new text constrait is set """ # TODO: implement the constraints again
    #     self.buffers[message["buf_id"]].text.handle_text_constraint(message)
    #     return

    # House keeping
    # =============

    def kill(self):
        """ Close socket connections and terminate the application """
        try:

            for buf in self.buffers.values():
                
                buf.lang.kill()
            
        except(Exception) as e:
            
            stdout(e.__class__.__name__, e)
        
        BasicInterface.kill(self)
        
        return

    def freeze_kill(self, err):
        ''' Displays an error message and stops communicating to the server '''
        self.console.write(err)
        self.client.send.kill()
        self.client.recv.kill()
        return

    def center(self):

        w = 1200
        h = 900

        ws = self.root.winfo_screenwidth()
        hs = self.root.winfo_screenheight()

        x = int((ws/2) - (w / 2))
        y = int((hs/2) - (h / 2))

        self.root.geometry('{}x{}+{}+{}'.format(w, h, x, y))

        # Try and start full screen (issues on Linux)

        try:

            self.root.state("zoomed")

        except Tk.TclError:

            pass

        return

    def user_disabled(self):
        """ Returns True if user is blocked from applying operations etc """
        return self.block_messages # to-do: update variable name

    @staticmethod
    def convert(index):
        """ Converts a Tkinter index into a tuple of integers """
        return tuple(int(value) for value in str(index).split("."))

    def init_local_user(self, id_num, name):
        """ Create the peer that is local to the client (text.marker) """

        try:

            self.local_peer = self.add_new_user(id_num, name)

        except ValueError:

            self.client.kill()

            print("Error: Maximum number of clients connected to server, please try again later.")

        return

    def add_new_user(self, user_id, name):
        """ Initialises a new Peer object """

        peer = self.client.peers[user_id] = Peer(user_id, name, self)

        # Draw marker

        peer.move(0, 0) # BufferTab, Index

        return peer

    def reconnect_user(self, user_id, name):
        """ Re-adds a disconnected user to the interface """
        peer = self.client.peers[user_id]
        peer.reconnect(name)
        peer.move(0, 0)
        return peer

    def reset_title(self):
        """ Resets any changes to the window's title """
        self.root.title(self.title)
        return

    # Sending messages to the server
    # ==============================

    def add_to_send_queue(self, message, wait=False):
        """ Sends message to server and evaluates them locally if not other markers
            are using the same line. Use the wait flag when you want to force the
            message to go to the server and wait for the response before continuing """

        # Call multiple times if we have a list

        if isinstance(message, list):

            for msg in message:

                self.add_to_send_queue(msg) # just in case we get nested lists somehow

        elif isinstance(message, MESSAGE):

            if self.user_disabled() is False or isinstance(message, MSG_CONNECT_ACK):

                self.msg_id += 1

                message.set_msg_id(self.msg_id)

                self.client.send_queue.put(message)

        else:

            raise TypeError("Must be MESSAGE or list")

        return

    def listen(self):
        """ Continuously reads from the queue of messages read from the server
            and carries out the specified actions. """

        try:
            while True:

                # Pop the message from the queue

                msg = self.queue.get_nowait()

                # Get the handler method and call

                try:

                    self.handle(msg)

                except Exception as e:

                    print("Exception occurred in message {!r}: {!r} {!r}".format(self.handles[msg.type].__name__, type(e), e))
                    raise(e)

                # Update any other idle tasks

                self.root.update_idletasks()

        # Break when the queue is empty
        except queue.Empty:

            pass

        # self.redraw()

        # Recursive call
        self.root.after(300, self.listen)
        return

    # Interface toggles
    # =================

    def toggle_transparency(self, event=None):
        """ Sets the text and console background to black and then removes all black pixels from the GUI """
        setting_transparent = self.transparent.get()
        if setting_transparent:
            if not self.using_alpha:
                alpha = "#000001" if SYSTEM == WINDOWS else "systemTransparent"
                self.text.config(background=alpha)
                self.line_numbers.config(background=alpha)
                self.console.config(background=alpha)
                self.graphs.config(background=alpha)
                if SYSTEM == WINDOWS:
                    self.root.wm_attributes('-transparentcolor', alpha)
                else:
                    self.root.wm_attributes("-transparent", True)
            else:
                self.root.wm_attributes("-alpha", float(COLOURS["Alpha"]))
        else:
            # Re-use colours
            if not self.using_alpha:
                self.text.config(background=COLOURS["Background"])
                self.line_numbers.config(background=COLOURS["Background"])
                self.console.config(background=COLOURS["Console"])
                self.graphs.config(background=COLOURS["Stats"])
                if SYSTEM == WINDOWS:
                    self.root.wm_attributes('-transparentcolor', "")
                else:
                    self.root.wm_attributes("-transparent", False)
            else:
                self.root.wm_attributes("-alpha", 1)
        return

    # Colour scheme changes
    # =====================

    def edit_colours(self, event=None):
        """ Opens up the colour options dialog """
        from .colour_picker import ColourPicker
        ColourPicker(self)
        return

    def ApplyColours(self, event=None):
        """ Update the IDE for the new colours """
        LoadColours() # from config.py
        # Text & Line numbers
        self.text.config(bg=COLOURS["Background"], insertbackground=COLOURS["Background"])
        self.line_numbers.config(bg=COLOURS["Background"])
        # Console
        self.console.config(bg=COLOURS["Console"])
        # Stats
        self.graphs.config(bg=COLOURS["Stats"])
        # Peers
        for peer in self.text.peers.values():
            peer.update_colours()
            peer.configure_tags()
            self.graphs.itemconfig(peer.graph, fill=peer.bg)
        return

    def get_peer(self, message):
        """ Retrieves the Peer instance using the "src_id" of message """

        this_peer = None

        if 'src_id' in message and message['src_id'] != -1:

            try:

                this_peer = self.peers[message['src_id']]

            except KeyError as err:

                self.freeze_kill(str(err))

        return this_peer

    # Misc.
    # =====

    def active_buffer(self):
        """ Returns the buffer that the local peer is in """
        return self.local_peer.get_buffer()

    def OpenGitHub(self, event=None):
        """ Opens the Troop GitHub page in the default web browser """
        webbrowser.open("https://github.com/Qirky/Polyglot")
        return

    def redraw(self):
        """ Calls redraw method for each buffer """
        for buf in self.buffers.values():
            buf.redraw()        
        return

    def configure_font(self):
        """ Sets up font for the editor """

        if SYSTEM == MAC_OS:

            fontfamily = "Monaco"

        elif SYSTEM == WINDOWS:

            fontfamily = "Consolas"

        else:

            fontfamily = "Courier New"

        self.font_names = []

        self.font = tkFont.Font(family=fontfamily, size=12, name="Font")
        self.font.configure(**tkFont.nametofont("Font").configure())
        self.font_names.append("Font")

        self.font_bold = tkFont.Font(family=fontfamily, size=12, weight="bold", name="BoldFont")
        self.font_bold.configure(**tkFont.nametofont("BoldFont").configure())
        self.font_names.append("BoldFont")

        self.font_italic = tkFont.Font(family=fontfamily, size=12, slant="italic", name="ItalicFont")
        self.font_italic.configure(**tkFont.nametofont("ItalicFont").configure())
        self.font_names.append("ItalicFont")

        self.font_console = tkFont.Font(family=fontfamily, size=12, name="ConsoleFont")
        self.font_console.configure(**tkFont.nametofont("ConsoleFont").configure())

        # self.root.configure(font="Font") # TODO this might be for

        self.bracket_style = {'borderwidth': 2, 'relief' : 'groove'}
        self.bracket_tag = "tag_open_brackets"

        return

    # def set_interpreter(self, name):
    #     """ Tells Troop to interpret a new language, takes a string """
    #     self.lang.kill()

    #     try:
    #         self.lang=langtypes[name]()

    #     except ExecutableNotFoundError as e:

    #         print(e)

    #         self.lang = DummyInterpreter()

    #     s = "Changing interpreted lanaguage to {}".format(repr(self.lang))
    #     print("\n" + "="*len(s))
    #     print(s)
    #     print("\n" + "="*len(s))

    #     self.lang.start()

    #     return

    # def set_constraint(self, name):
    #     """ Tells Troop to use a new character constraint, see `constraints.py` for more information. """
    #     self.add_to_send_queue(MSG_CONSTRAINT(self.text.marker.id, name))
    #     return

    # # Message logging
    # # ===============

    # def set_up_logging(self):
    #     """ Checks if there is a logs folder, if not this creates it """

    #     log_folder = os.path.join(ROOT_DIR, "logs")

    #     if not os.path.exists(log_folder):

    #         os.mkdir(log_folder)

    #     # Create filename based on date and times

    #     self.fn = time.strftime("client-log-%d%m%y_%H%M%S.txt", time.localtime())
    #     path    = os.path.join(log_folder, self.fn)

    #     self.log_file   = open(path, "w")
    #     self.is_logging = True

    # def log_message(self, message):
    #     """ Logs a message to the widget's log_file with a timestamp """
    #     self.log_file.write("%.4f" % time.time() + " " + repr(str(message)) + "\n")
    #     return

    # def ImportLog(self):
    #     """ Imports a logfile generated by run-server.py --log and 'recreates' the performance """
    #     logname = tkFileDialog.askopenfilename()
    #     self.logfile = Log(logname)
    #     self.logfile.set_marker(self.text.marker)
    #     self.logfile.recreate()
    #     return
