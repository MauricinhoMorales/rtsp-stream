import sys
import gi
import os

gi.require_version("Gst", "1.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkX11", "3.0")
gi.require_version("GstVideo", "1.0")

from gi.repository import Gst, Gtk, GLib, GdkX11, GstVideo
from dotenv import load_dotenv

class Player(object):
    def __init__(self):
        # Initialize GTK
        Gtk.init(sys.argv)

        # Initialize GStreamer
        Gst.init(sys.argv)

        self.state = Gst.State.NULL
        self.duration = Gst.CLOCK_TIME_NONE
        self.pipeline = Gst.ElementFactory.make("playbin", "pipeline")
        if not self.pipeline:
            print("ERROR: Could not create pipeline.")
            sys.exit(1)

        # Set up parameters of pipeline
        load_dotenv()
        self.pipeline.set_property("uri", os.getenv("RTSP_URI"))
        self.pipeline.set_property("av-offset", -1000000000)

        # Command to execute the Pipeline in GST-LAUNCH
        # gst-launch-1.0 rtspsrc location=rtsp://192.168.101.9:8554/stream latency=0 name=src src. ! 
        # rtph264depay ! h264parse ! avdec_h264 ! queue ! autovideosink src. ! 
        # rtpmpadepay ! mpegaudioparse !  mpg123audiodec ! audioconvert ! audioresample ! queue ! autoaudiosink
        
        # Connect to tag changes signals
        self.pipeline.connect("video-tags-changed", self.on_tags_changed)
        self.pipeline.connect("audio-tags-changed", self.on_tags_changed)

        # Connect to error signals
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self.on_error)
        bus.connect("message::eos", self.on_eos)
        bus.connect("message::state-changed", self.on_state_changed)
        bus.connect("message::application", self.on_application_message)
        
        # Create the GUI
        self.build_ui()

    # Function to set the pipeline to PLAYING and refresh UI
    def start(self):
        # Start playing
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            print("ERROR: Unable to set the pipeline to the playing state")
            sys.exit(1)

        # Register a function that GLib will call every second
        GLib.timeout_add_seconds(1, self.refresh_ui)

        # Start the GTK main loop
        Gtk.main()

        # Free resources
        self.cleanup()

    # Function to set the pipeline state to NULL and remove it
    def cleanup(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None

    # Function to create a basic GUI
    def build_ui(self):
        main_window = Gtk.Window.new(Gtk.WindowType.TOPLEVEL)
        main_window.connect("delete-event", self.on_delete_event)

        # Create the window to show the video
        video_window = Gtk.DrawingArea.new()
        video_window.connect("realize", self.on_realize)
        video_window.connect("draw", self.on_draw)

        # Create the buttons
        play_button = Gtk.Button.new_with_label("PLAY")
        play_button.connect("clicked", self.on_play)
        pause_button = Gtk.Button.new_with_label("PAUSE")
        pause_button.connect("clicked", self.on_pause)

        # Create the text where the data will be show
        self.streams_list = Gtk.TextView.new()
        self.streams_list.set_editable(False)

        # Linked all the items of the GUI
        controls = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        controls.pack_start(play_button, True, False, 2)
        controls.pack_start(pause_button, True, False, 2)

        main_vbox = Gtk.Box.new(Gtk.Orientation.VERTICAL, 0)
        main_vbox.pack_start(self.streams_list, False, False, 2)
        main_vbox.pack_start(controls, False, False, 0)
            
        main_box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 0)
        main_box.pack_start(video_window, True, True, 0)
        main_box.pack_start(main_vbox, False, False, 0)

        # Added the linked items into the window
        main_window.add(main_box)
        main_window.set_default_size(640, 480)
        main_window.show_all()

    # Function to recieve the video into the window previously created
    def on_realize(self, widget):
        window = widget.get_window()
        window_handle = window.get_xid()

        self.pipeline.set_window_handle(window_handle)

    # Function called to draw when not in PAUSED or PLAYING state
    def on_draw(self, widget, cr):
        if self.state < Gst.State.PAUSED:
            allocation = widget.get_allocation()

            cr.set_source_rgb(0, 0, 0)
            cr.rectangle(0, 0, allocation.width, allocation.height)
            cr.fill()

        return False
    
    # Function called when the PLAY button is clicked
    def on_play(self, button):
        self.pipeline.set_state(Gst.State.PLAYING)
        pass

    # Function called when the PAUSE button is clicked
    def on_pause(self, button):
        self.pipeline.set_state(Gst.State.PAUSED)
        pass

    # Function called when the main window is closed
    def on_delete_event(self, widget, event):
        Gtk.main_quit()

    # Function called periodically to refresh the GUI
    def refresh_ui(self):
        current = -1
        
        if self.state < Gst.State.PAUSED:
            return True

    # Function called if new metadata is discovered in the stream
    def on_tags_changed(self, pipeline, stream):
        self.pipeline.post_message(
            Gst.Message.new_application(
                self.pipeline, Gst.Structure.new_empty("tags-changed")
            )
        )

    # Function called when an error message is posted on the bus
    def on_error(self, bus, msg):
        err, dbg = msg.parse_error()
        print("ERROR:", msg.src.get_name(), ":", err.message)
        if dbg:
            print("Debug info:", dbg)

    # Function is called when an End-Of-Stream message is posted on the bus
    def on_eos(self, bus, msg):
        print("End-Of-Stream reached")
        self.pipeline.set_state(Gst.State.READY)

    # Function called when the pipeline changes states.
    def on_state_changed(self, bus, msg):
        old, new, pending = msg.parse_state_changed()
        if not msg.src == self.pipeline:
            # not from the pipeline, ignore
            return

        self.state = new
        print(
            "State changed from {0} to {1}".format(
                Gst.Element.state_get_name(old), Gst.Element.state_get_name(new)
            )
        )

        if old == Gst.State.READY and new == Gst.State.PAUSED:
            self.refresh_ui()

    # Function to extract metadata from all the streams and write it to the text widget
    def analyze_streams(self):
        # clear current contents of the widget
        buffer = self.streams_list.get_buffer()
        buffer.set_text("")

        # read some properties
        nr_video = self.pipeline.get_property("n-video")
        nr_audio = self.pipeline.get_property("n-audio")

        for i in range(nr_video):
            tags = None
            # Get the stream video tags
            tags = self.pipeline.emit("get-video-tags", i)
            if tags:
                buffer.insert_at_cursor("Video stream{0}\n".format(i))
                # buffer.insert_at_cursor("\nParameters: {0}\n".format(tags.to_string()))
                self.set_parameter(buffer, tags.get_string,Gst.TAG_VIDEO_CODEC)
                self.set_parameter(buffer, tags.get_uint,Gst.TAG_MINIMUM_BITRATE)
                self.set_parameter(buffer, tags.get_uint,Gst.TAG_MAXIMUM_BITRATE )
                self.set_parameter(buffer, tags.get_uint,Gst.TAG_BITRATE)
                
        for i in range(nr_audio):
            tags = None
            # Get the stream audio tags
            tags = self.pipeline.emit("get-audio-tags", i)
            if tags:
                buffer.insert_at_cursor("\nAudio stream{0}\n".format(i))
                # buffer.insert_at_cursor("\nParameters: {0}\n".format(tags.to_string()))
                self.set_parameter(buffer, tags.get_string,Gst.TAG_AUDIO_CODEC)
                self.set_parameter(buffer, tags.get_uint,Gst.TAG_NOMINAL_BITRATE)
                self.set_parameter(buffer, tags.get_uint,Gst.TAG_MINIMUM_BITRATE)
                self.set_parameter(buffer, tags.get_uint,Gst.TAG_MAXIMUM_BITRATE )
                self.set_parameter(buffer, tags.get_uint,Gst.TAG_BITRATE)

    def set_parameter(self, buffer, fn, tag):
        ret, str = fn(tag)
        if ret:
            buffer.insert_at_cursor("{0} :".format(tag))
            buffer.insert_at_cursor("{0}\n".format(str))

    # Function called when an "application" message is posted on the bus
    def on_application_message(self, bus, msg):
        if msg.get_structure().get_name() == "tags-changed":
            # if the message is the "tags-changed", update the GUI
            self.analyze_streams()


if __name__ == "__main__":
    p = Player()
    p.start()
