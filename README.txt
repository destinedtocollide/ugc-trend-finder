UGC TREND FINDER  v1.2
======================

Finds trending Roblox UGC themes and suggests items to make, with prices,
colors and pictures of the items that are selling.

This folder is the app's source. You put it on GitHub once; GitHub then builds
a normal installer (UGC-Trend-Finder-Setup.exe) and every installed copy keeps
itself up to date. Everything below happens in your web browser. No terminal.


ONE-TIME SETUP (about 10 minutes)
---------------------------------
1. Make a free account at https://github.com and sign in.

2. Create the repository:
   - Top right "+" > "New repository".
   - Name: ugc-trend-finder
   - Choose "Public" (the app needs to be able to download updates).
   - Click "Create repository".

3. Upload the files:
   - On the new repository page, click "uploading an existing file".
   - Open this folder in File Explorer, select EVERYTHING inside it
     (Ctrl+A, including the ".github" folder) and drag it onto the page.
   - Click "Commit changes".
   - Check that you see a ".github" folder in the file list. If it's missing
     (some browsers skip it): click "Add file" > "Create new file", type
     .github/workflows/build.yml as the name, paste the contents of that
     file from this folder, and click "Commit changes".

4. Publish the first release:
   - On the repository page, click "Releases" (right side) >
     "Create a new release".
   - "Choose a tag": type  v1.2  and click "Create new tag".
   - Title: v1.2  (write anything you like in the description).
   - Click "Publish release".

5. Wait about 5 minutes. GitHub builds the installer by itself (you can
   watch it under the "Actions" tab). When it's done,
   UGC-Trend-Finder-Setup.exe appears on the release page.

6. Download UGC-Trend-Finder-Setup.exe and double-click it. That's it.
   Share the release page link with friends; they only need that .exe.

   Windows may show "Windows protected your PC" the first time. Click
   "More info" > "Run anyway". That happens with every new program that
   isn't from a big company.


HOW UPDATES WORK FROM NOW ON
----------------------------
When you get a new version from me:
1. On your repository page: "Add file" > "Upload files", drag in the new
   files, "Commit changes".
2. "Releases" > "Draft a new release", tag = the new version (for example
   v1.3), "Publish release".
Within a few hours every installed copy downloads it and restarts on the
new version. The app checks at startup and every 6 hours. You can also press
"Check for updates" in Settings. Turn automatic installs off in Settings if
you'd rather click "Install" yourself.


USING THE APP
-------------
- New scan: choose what to scan and press Start. You see the elapsed time,
  time left, which list it's reading, and a countdown if Roblox asks it to
  pause. A pause is normal; it continues on its own.
- Ideas: ranked ideas with a picture, price, colors, reasons and example
  items. Click any picture for a closer look or to open it on Roblox.
- Trending themes, History, Settings, How it works.
- Closing the window keeps it in the tray (next to the clock). Right-click
  the tray icon to open, scan or quit.

Reports are saved in Documents\UGC Trend Finder. If something goes wrong,
the details are written to %LOCALAPPDATA%\UGC Trend Finder\app.log.


RUNNING WITHOUT INSTALLING (for testing)
----------------------------------------
With Python installed, double-click "UGC Trend Finder.pyw". The first start
installs three helper packages (takes about a minute).
