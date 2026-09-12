import pyotherside
import time
import os
import threading
import sys
sys.path.append('deps')
sys.path.append('../deps')
import pexpect
import subprocess
import urllib.request
import shutil

import password_type

class Installer:
    click_rootdir = os.getcwd()

    def needs_custom_images(self) -> bool:
        if os.uname().machine != "aarch64": # images only compiled for arm64
            return False

        if shutil.which("getprop") is None:
            return False

        try:
            vendor_apilevel = int(subprocess.check_output(["getprop", "ro.vndk.version"]))
        except ValueError:
            try:
                vendor_apilevel = int(subprocess.check_output(["getprop", "ro.vendor.build.version.sdk"]))
            except ValueError:
                return False

        if vendor_apilevel <= 33: # only concerns Android 14+ based ports atm
            return False

        try:
            c = urllib.request.urlopen("https://ota.waydro.id/vendor/waydroid_arm64/HALIUM_14.json")
            c.close()
            return False
        except urllib.error.HTTPError as e:
            return e.code == 404

    def supports_a16_images(self) -> bool:
        with open("/usr/lib/waydroid/tools/helpers/lxc.py", "r") as f:
            return 'vintf' in f.read() # https://github.com/waydroid/waydroid/pull/2410 shipped on UT already

    def get_password_type(self):
        return password_type.get_password_type()

    def install(self, password, gAPPS, needsCustomImages):
        os.chdir("/home/phablet")

        #Starting bash and getting root privileges
        print("Starting bash and getting root privileges")
        pyotherside.send('state', 'starting', False)
        child = pexpect.spawn('bash')
        child.logfile_read = sys.stdout.buffer
        child.expect(r'\$')
        child.sendline('sudo -s')
        if password != '':
            child.expect('[p/P]ass.*')
            child.sendline(str(password))
        child.expect('root.*')

        #Initializing waydroid (downloading lineage)
        def download():
            waydroid = f"python3 {self.click_rootdir}/src/waydroid-custom-init" if needsCustomImages else "waydroid"
            if gAPPS == True:
                print("Initializing waydroid with GAPPS (downloading lineage)")
                pyotherside.send('state', 'dl.init.gapps', True)
                child.sendline(f"{waydroid} init -s GAPPS")
            else:
                print("Initializing waydroid (downloading lineage)")
                pyotherside.send('state', 'dl.init.vanilla', True)
                child.sendline(f"{waydroid} init")

        def dlstatus():
            print("Download status running")
            downloaded = []
            startedDownload = False

            def wait_for_extract(image):
                if not image in downloaded:
                    pyotherside.send('state', 'validate.' + image, False)
                    child.expect("Extracting to")
                    pyotherside.send('state', 'extract.' + image, False)
                    downloaded.append(image)

            while True:
                if not startedDownload:
                    index = child.expect(['Already initialized', pexpect.EOF, pexpect.TIMEOUT], timeout=1)
                    if index == 0:
                        # already initialized
                        break

                index = child.expect(['\r\[Downloading\]\s+([\d\.]+) MB/([\d\.]+) MB\s+([\d\.]+) ([km]bps)\(approx.\)$', pexpect.EOF, pexpect.TIMEOUT], timeout=1)
                if index == 0:
                    startedDownload = True
                    if 'system' in downloaded:
                        pyotherside.send('state', 'dl.vendor', True)
                    else:
                        pyotherside.send('state', 'dl.gapps' if gAPPS == True else 'dl.vanilla', True)

                    progress = float(child.match.group(1))
                    target = float(child.match.group(2))
                    speed = float(child.match.group(3))
                    unit = child.match.group(4)

                    pyotherside.send('downloadProgress', progress, target, speed, unit)

                index = child.expect(["Validating system image", pexpect.EOF, pexpect.TIMEOUT], timeout=0.5)
                if index == 0:
                    wait_for_extract('system')
                index = child.expect(["Validating vendor image", pexpect.EOF, pexpect.TIMEOUT], timeout=0.5)
                if index == 0:
                    wait_for_extract('vendor')

                if 'system' in downloaded and 'vendor' in downloaded:
                    break

        trd1 = threading.Thread(target=download)
        trd2 = threading.Thread(target=dlstatus)

        trd1.start()
        trd2.start()

        #wait for the threads to finish
        trd1.join()
        trd2.join()
        child.expect("root.*", timeout=300)
        child.close()

        pyotherside.send('state', 'complete', False)

        return ""
    
    def uninstall(self, password, wipe=False):
        os.chdir("/home/phablet")

        #Starting bash and getting root privileges
        print("Starting bash and getting root privileges")
        pyotherside.send('state', 'starting', False)
        child = pexpect.spawn('bash')
        child.logfile_read = sys.stdout.buffer
        child.expect(r'\$')
        child.sendline('sudo -s')
        if password != '':
            child.expect('[p/P]ass.*')
            child.sendline(str(password))
        child.expect('root.*')

        #Stop Waydroid Container
        print("stopping waydroid container")
        pyotherside.send('state', 'container', False)
        child.sendline("systemctl stop waydroid-container")
        child.expect("root.*", timeout=180)

        #do cleanup
        print("cleaning")
        pyotherside.send('state', 'cleanup', False)
        child.sendline("rm -rf /var/lib/waydroid/*")
        child.expect('root.*')
        if os.path.isdir("/etc/waydroid-extra"):
            child.sendline("rm -rf {/userdata/system-data,}/etc/waydroid-extra/*")
            child.expect('root.*')
        child.sendline("rm -f /home/phablet/.local/share/applications/Waydroid.desktop")
        child.expect('root.*')

        if wipe:
            child.sendline("rm -rf /home/phablet/.local/share/waydroid")
            child.expect('root.*')
            child.sendline("rm -rf /home/phablet/.local/share/applications/waydroid.*.desktop")
            child.expect('root.*')
            child.sendline("rm -f /home/phablet/.local/share/applications/stop-waydroid.desktop")
            child.expect('root.*')

        pyotherside.send('state', 'complete', False)
        child.close()

installer = Installer()
