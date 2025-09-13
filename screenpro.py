import os
import shlex
import signal
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from datetime import datetime
from shutil import which as shutil_which

# ---------- Helpers ----------
def is_wayland():
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"

def which(cmd):
    return shutil_which(cmd) is not None

def detect_screen_size_fallback(root):
    root.update_idletasks()
    return root.winfo_screenwidth(), root.winfo_screenheight()

def log_event(message):
    log_dir = os.path.expanduser("~/Videos/Record")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "record.log")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a") as f:
        f.write(f"[{timestamp}] {message}\n")

# ---------- Build Commands ----------
def build_cmd_x11(out_path, fps, size_str, display=":0.0", audio="default", webcam="/dev/video0"):
    """Screen + audio + webcam overlay (top-right,rectangular)."""
    webcam_w, webcam_h = 300, 300
    x_pos, y_pos = "(main_w-overlay_w-20)", "20"

    cmd = (
        f'ffmpeg -y '
        f'-video_size {size_str} -framerate {fps} -f x11grab -i {display} '       # Screen
        f'-f v4l2 -video_size {webcam_w}x{webcam_h} -i {webcam} '                 # Webcam
        f'-f pulse -thread_queue_size 512 -ac 2 -i {audio} '                      # Audio
        f'-filter_complex "[0:v][1:v] overlay={x_pos}:{y_pos}[v]" '               # Overlay webcam
        f'-map "[v]" -map 2:a '
        f'-c:v libx264 -preset veryfast -pix_fmt yuv420p -crf 23 '
        f'-c:a aac -b:a 160k '
        f'"{out_path}"'
    )
    return cmd

def build_cmd_wayland(out_path, fps, size_str, audio="default"):
    """Fallback for Wayland (wf-recorder only, no webcam overlay)."""
    cmd = (
        f'wf-recorder -f "{out_path}" '
        f'--audio={audio} --framerate {fps} --pixel-format yuv420p'
    )
    return cmd

# ---------- GUI App ----------
class RecorderGUI:
    def __init__(self):
        self.proc = None
        self.output_file = None
        self.title_text = ""
        self.paused = False

        self.root = tk.Tk()
        self.root.title("🎬 Screen Recorder Pro")
        self.root.resizable(False, False)

        default_dir = os.path.expanduser("~/Videos/Record")
        default_fps = "30"
        w, h = detect_screen_size_fallback(self.root)
        self.size_str = tk.StringVar(value=f"{w}x{h}")
        self.output_dir = tk.StringVar(value=default_dir)
        self.fps = tk.StringVar(value=default_fps)

        pad = {'padx': 10, 'pady': 6}
        tk.Label(self.root, text="Output directory").grid(row=0, column=0, sticky="w", **pad)
        tk.Entry(self.root, textvariable=self.output_dir, width=40).grid(row=0, column=1, **pad)
        tk.Button(self.root, text="Browse", command=self.browse_dir).grid(row=0, column=2, **pad)

        tk.Label(self.root, text="FPS").grid(row=1, column=0, sticky="w", **pad)
        tk.Spinbox(self.root, from_=10, to=120, textvariable=self.fps, width=10).grid(row=1, column=1, sticky="w", **pad)

        tk.Label(self.root, text="Screen size").grid(row=2, column=0, sticky="w", **pad)
        tk.Entry(self.root, textvariable=self.size_str, width=12).grid(row=2, column=1, sticky="w", **pad)
        tk.Label(self.root, text="(auto-detected; keep as is)").grid(row=2, column=2, sticky="w", **pad)

        self.status = tk.StringVar(value="Ready")
        tk.Label(self.root, textvariable=self.status, fg="gray").grid(row=3, column=0, columnspan=3, sticky="w", **pad)

        self.btn_start = tk.Button(self.root, text="Start Recording", command=self.start_recording, width=18)
        self.btn_stop = tk.Button(self.root, text="Stop", command=self.stop_recording, state="disabled", width=10)
        self.btn_pause = tk.Button(self.root, text="Pause", command=self.toggle_pause, state="disabled", width=10)
        self.btn_start.grid(row=4, column=0, **pad)
        self.btn_stop.grid(row=4, column=1, sticky="w", **pad)
        self.btn_pause.grid(row=4, column=2, sticky="w", **pad)
        tk.Button(self.root, text="Quit", command=self.on_quit, width=8).grid(row=5, column=2, sticky="e", **pad)

        self.root.bind("<Control-s>", lambda e: self.start_recording())
        self.root.bind("<Control-q>", lambda e: self.stop_recording())
        self.root.bind("<Control-p>", lambda e: self.toggle_pause())
        self.root.protocol("WM_DELETE_WINDOW", self.on_quit)

    def browse_dir(self):
        d = filedialog.askdirectory(initialdir=self.output_dir.get())
        if d:
            self.output_dir.set(d)

    def start_recording(self):
        if self.proc is not None:
            messagebox.showwarning("Already running", "Recording is already in progress.")
            return

        self.title_text = simpledialog.askstring("Video Title", "Enter video title:")
        if not self.title_text:
            messagebox.showerror("Missing", "Please enter a video title.")
            return

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"recording_{ts}.mp4"
        out_dir = self.output_dir.get().strip()
        fps = self.fps.get().strip()
        size_str = self.size_str.get().strip()

        os.makedirs(out_dir, exist_ok=True)
        self.output_file = os.path.join(out_dir, filename)

        if is_wayland():
            if not which("wf-recorder"):
                messagebox.showerror("wf-recorder not found",
                    "You are on Wayland and 'wf-recorder' is not installed.\n\nInstall it: sudo apt install wf-recorder")
                log_event("Failed: wf-recorder not found")
                return
            cmd = build_cmd_wayland(self.output_file, fps, size_str)
        else:
            if not which("ffmpeg"):
                messagebox.showerror("FFmpeg not found",
                    "FFmpeg is required on X11.\n\nInstall it: sudo apt install ffmpeg")
                log_event("Failed: FFmpeg not found")
                return
            display = os.environ.get("DISPLAY", ":0.0")
            cmd = build_cmd_x11(self.output_file, fps, size_str, display=display)

        try:
            self.status.set("Recording… (Ctrl+Q to stop)")
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
            self.btn_pause.config(state="normal")
            self.root.update()

            args = shlex.split(cmd)
            self.proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1
            )
            self.paused = False
            log_event(f"Started recording: {self.output_file}")
        except Exception as e:
            self.proc = None
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.btn_pause.config(state="disabled")
            messagebox.showerror("Error starting recorder", str(e))
            log_event(f"Failed to start recording: {e}")

    def toggle_pause(self):
        if self.proc is None:
            return
        if not self.paused:
            try:
                self.proc.send_signal(signal.SIGSTOP)
                self.status.set("Paused")
                self.btn_pause.config(text="Resume")
                log_event("Recording paused")
                self.paused = True
            except Exception as e:
                messagebox.showerror("Pause Error", str(e))
                log_event(f"Failed to pause recording: {e}")
        else:
            try:
                self.proc.send_signal(signal.SIGCONT)
                self.status.set("Recording… (Ctrl+Q to stop)")
                self.btn_pause.config(text="Pause")
                log_event("Recording resumed")
                self.paused = False
            except Exception as e:
                messagebox.showerror("Resume Error", str(e))
                log_event(f"Failed to resume recording: {e}")

    def stop_recording(self):
        if self.proc is None:
            return

        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_pause.config(state="disabled")
        self.status.set("Stopping...")

        try:
            if is_wayland():
                self.proc.send_signal(signal.SIGINT)
            else:
                if self.proc.stdin:
                    try:
                        self.proc.stdin.write('q\n')
                        self.proc.stdin.flush()
                    except Exception:
                        self.proc.send_signal(signal.SIGINT)

            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()

            # 5s splash
            final_file = self.output_file.replace(".mp4", "_final.mp4")
            splash_file = "splash.mp4"
            cmd_splash = (
                f'ffmpeg -y -f lavfi -i color=c=black:s={self.size_str.get()}:d=5 '
                f'-f lavfi -i anullsrc=r=44100:cl=stereo '
                f'-vf "drawtext=text=\'{self.title_text}\':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2" '
                f'-c:v libx264 -c:a aac -shortest "{splash_file}"'
            )
            subprocess.run(shlex.split(cmd_splash), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            with open("concat_list.txt", "w") as f:
                f.write(f"file '{splash_file}'\n")
                f.write(f"file '{self.output_file}'\n")

            subprocess.run(shlex.split(
                f'ffmpeg -y -f concat -safe 0 -i concat_list.txt -c copy "{final_file}"'
            ), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            os.remove(splash_file)
            os.remove("concat_list.txt")
            os.remove(self.output_file)
            self.output_file = final_file

            if os.path.exists(self.output_file):
                self.status.set(f"Saved: {self.output_file}")
                print(f"✅ Recording saved: {self.output_file}")
                log_event(f"Success: Recording saved: {self.output_file}")
            else:
                self.status.set("Error: file not saved")
                print("❌ Error: final video not created")
                log_event("Failed: final video not created")

        except Exception as e:
            print(f"❌ Stop error: {e}")
            log_event(f"Failed during stop: {e}")
        finally:
            self.proc = None
            self.paused = False
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.btn_pause.config(state="disabled")
            self.btn_pause.config(text="Pause")

    def on_quit(self):
        if self.proc is not None:
            if messagebox.askyesno("Quit", "Recording is running. Stop and quit?"):
                self.stop_recording()
                self.root.after(100, self.root.destroy)
        else:
            self.root.destroy()

    def run(self):
        self.root.mainloop()

# ---------- Main ----------
if __name__ == "__main__":
    app = RecorderGUI()
    app.run()
