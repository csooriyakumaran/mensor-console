import os
import sys
import stat
import subprocess
import time
import threading
import re
import logging
import logging.config
from datetime import datetime
from collections import deque
from dataclasses import dataclass
# ---
import click
import easygui
import serial
import numpy as np
import matplotlib.pyplot as plt
from serial.threaded import ReaderThread, LineReader
from serial.tools import list_ports
from aiolos_code_instrumentation import aiolos_logging
# ---

log = logging.getLogger(__name__)

mpl_logger = logging.getLogger('matplotlib')
mpl_logger.setLevel(logging.WARNING)
pil_logger = logging.getLogger('PIL')
pil_logger.setLevel(logging.WARNING)


@dataclass
class Packet:
    ts: float
    p1: float
    p2: float

class MensorCGP2300:

    def __init__(self, port, baudrate, databits, parity, stopbits):
        self.port     = port 
        self.baudrate = baudrate
        self.databits = databits
        self.parity   = parity
        self.stopbits = stopbits

        self.running   = True
        self.connected = False
        self.scanning  = False
        self.writing   = True
        self.status    = ''

        self.sendqueue = deque()
        self.dataqueue = deque()
        self.data_cache = np.array([], dtype=Packet)
        self.ts_start  = time.time()

        self.serial_connection = serial.Serial()

        self.frames_read = 0

        self.file = None
        self.bytes_written = 0

        self.file_writer = threading.Thread(target=self.write_to_file)

        SerialThreadedReader.on_connected_callback    = self.on_connected
        SerialThreadedReader.on_disconnected_callback = self.on_disconnected
        SerialThreadedReader.on_data_callback         = self.on_data_recieved
        
    def __del__(self):
        if self.running:
            self.shutdown()

    def shutdown(self):
        log.warning('Shutting down device ..')
        self.writing = False
        if self.file_writer.is_alive():
            log.warning('killing the file writer thread')
            self.file_writer.join()
        #- close open file
        if self.file and not self.file.closed:
            log.warning('Closing file {}'.format(self.file.name))
            self.file.close()

        #- close serial port
        if self.serial_connection.is_open:
            log.warning('closing serial connection on port {}'.format(self.serial_connection.port))
            self.reader.stop()
            self.serial_connection.close()

        self.connected = False
        self.running = False


    def connect(self):

        if not self.port:
            ports = list_ports.comports()

            if not ports:
                log.warning('--- No Serial Ports Available ---')
                return

            print('--- Available Serial Ports ---')
            print('------------------------------')
            for i,v in enumerate(ports):
                print('  {}: {} | {} | {}'.format(i, v[0], v[1], v[2]))

            raw = input('\n--- Select port index (ctrl-c to exit) $ ')
            print('------------------------------\n')
            try:
                n = int(raw)
                self.port = ports[n][0]
            except:
                log.error('--- Error: Invalid Entry ---')
                return 

        try:
            self.serial_connection.port     = self.port 
            self.serial_connection.baudrate = self.baudrate
            self.serial_connection.bytesize = self.databits
            self.serial_connection.parity   = self.parity
            self.serial_connection.stopbits = self.stopbits
            self.serial_connection.timeout  = 0.1

            self.serial_connection.open()

            self.reader = ReaderThread(self.serial_connection, SerialThreadedReader)
            self.reader.start()

            self.file_writer.start()
        
        except IOError as e:
            log.error(e)
            self.shutdown()
            raise e


    def on_connected(self):
        self.connected = True
        log.warning('--- Serial connection on {} sucessfully established.  ---'.format(self.port))
        log.debug('port:     {}'.format(self.port))
        log.debug('baudrate: {}'.format(self.baudrate))
        log.debug('databits: {}'.format(self.databits))
        log.debug('parity:   {}'.format(self.parity))
        log.debug('stopbits: {}'.format(self.stopbits))

    def on_disconnected(self):
        self.connected = False
        self.serial_connection = serial.Serial()
        log.error('--- Serial connection on {} disconnected! ---'.format(self.port))

    def on_data_recieved(self, data):
        self.frames_read += 1
        self.dataqueue.append(data);
        log.debug('data added to queu: ts {}, p1 {}, p2{}'.format(data.ts - self.ts_start, data.p1, data.p2))
            



    def parse_args(self, args):


        if len(args) == 0:
            args = [args]

        if args[0] == 'scan':
            count = 300
            rate = 10
            if len(args) > 1:
                count = args[1]
            if len(args) > 2:
                rate = args[2]

            self.scanning = True
            try:
                self.scan(int(count), float(rate))
            except Exception as e:
                 log.error(e)

        elif args[0] == 'shell':
            exe = r'"C:\\Program Files\\PowerShell\\7\\pwsh.exe"'
            print(exe)
            print(' '.join(args[1::]))
            # if len(args) < 2:
            #    log.error('shell command requires additional arguments')
            #    return
            subprocess.call(' '.join(args[1::]), shell=True, executable=exe)
                 
        elif args[0] == 'pwd':
            print(os.getcwd())

        elif args[0] == 'cd':
            if len(args) > 1:
                path = args[1]
                if not os.path.isdir(path):
                    log.warning('Directory {} does not exist'.format(path))
                    raw = input('Create directory? y/n >>> ')
                    # print ("\033[A                                                                   \033[A")

                    if 'yes' == raw.lower() or 'y' == raw.lower():
                        if not os.path.isabs(args[1]):
                            path = os.getcwd() + "\\" + path
                        os.mkdir(path)
                    else:
                        return

                os.chdir(path)
            else:
                log.error('cd requires one argument [path-to-directory]')

        elif args[0] == 'clear':
            os.system('cls' if os.name == 'nt' else 'clear')

        elif args[0] == 'll' or args[0] == 'ls':
            for entry in os.scandir():
                print('{}\t{}\t{} bytes \t\t{}'.format(stat.filemode(entry.stat().st_mode), datetime.fromtimestamp(entry.stat().st_ctime), entry.stat().st_size, entry.name))
                
        elif args[0] == 'logdebug':
            aiolos_logging.change_all_logging_levels(logging.DEBUG)

        elif args[0] == 'loginfo':
            aiolos_logging.change_all_logging_levels(logging.INFO)



        elif args[0] == 'open':
            path = ''
            mode = 'w'
            if len(args) > 1:
                 path = args[1]
            if len(args) > 2:
                 mode = args[2]
            self.open_file(path, mode)

        elif args[0] == 'save':
            if len(args) > 1:
                 self.file.name = args[1]
            self.dump_to_file()

        elif args[0] == 'close':
            self.close_file()

        elif args[0] == 'print':
            if not self.dataqueue:
                log.warning('no data to print')
                return
            for data in self.dataqueue:
                log.info(data)

        elif args[0] == 'plot':
            self.plot()

        elif args[0] == 'clearq':
            self.clear_data()

        elif args[0] == 'send':
            if len(args) < 2:
                log.error('send requires one additional argument [Mensor-command-or-query-string]')
            else:
                cmd = '#*' + args[1] + '\r\n'
                self.reader.write(cmd.encode('ascii'))
        else:
            log.error('invalid command')

        


    def runloop(self):

        while self.connected:
            time.sleep(0.1) 
            print('{}'.format(os.getcwd()), end='')
            if self.file:
                print(' ({}) '.format(self.file.name), end='')
            print(' [{} frames in buffer, {} bytes written] '.format(len(self.dataqueue), self.bytes_written), end ='')
            raw = input(' $ ')
            # print ("\033[A                                                                   \033[A")

            args = raw.split()

            if not args:
                continue

            args[0] = args[0].lower()

            if args[0] == 'quit' or args[0] == 'exit':
                self.shutdown()
                break
            
            self.parse_args(args)


    def scan(self, count, rate):

        self.frames_read = 0
        t = 0
        self.ts_start = time.time()
        t0 = self.ts_start

        log.info('scanning {} frames at {} Hz'.format(count, rate))
        for i in range(count):
            if not self.scanning:
                return
            
            t0 = time.time()
            self.reader.write('#*?\r\n'.encode('ascii'))
            log.info('frame {} of {} requested'.format(i, count))

            dt = time.time() - t0
            while dt < (1.0/rate):
                dt = time.time() - t0
            # time.sleep(1.0/rate)
        time.sleep(1.0/rate)
        log.info('{} frames read in'.format(self.frames_read))
        self.scanning = False

    def clear_data(self):
        log.warning('clearing data from the queue')
        self.dataqueue.clear()

    def open_file(self, path = '', mode='w'):

        if self.file and not self.file.closed:
            log.error('A file is already open, close it to open a new file')
            return

        if not path:
            path = easygui.filesavebox(
                    msg = 'Select output file for Mensor CGP2300',
                    title = 'Open Data File',
                    filetypes = ['*.dat']
                    )

        if not path:
            log.warning('Must specify path of file to open')
            return

        try:
            if self.dataqueue:
                log.warning('data in the buffer..')
                raw = input('write data buffer to file? (y/n) $ ')
                if raw.lower() == 'n' or raw.lower() == 'no':
                    log.error('no file opened')
                    return
            self.file = open(path, mode)
        except IOError as e:
            log.error(e)
            return

        # self.dataqueue.clear()
        self.bytes_written = 0
        self.writing = True
        
        log.warning('file opened: {}'.format(self.file.name))

    def write_to_file(self):
        while self.writing:
            while self.dataqueue and (self.file and not self.file.closed):
                data = self.dataqueue.popleft()
                self.file.write('{}, {}, {}\n'.format(data.ts - self.ts_start, data.p1, data.p2))
                self.bytes_written += sys.getsizeof(data.ts) 
                self.bytes_written += sys.getsizeof(data.p1) 
                self.bytes_written += sys.getsizeof(data.p2) 

    def dump_to_file(self):
        if not self.file:
            self.open_file()
        
        if not self.file:
            log.error('No open file to write to')
            return

        if not self.dataqueue:
            log.warning('no data to write to file')
            return


        while self.dataqueue:
            data = self.dataqueue.popleft()
            self.file.write('{}, {}, {}\n'.format(data.ts, data.p1, data.p2))
            self.bytes_written += sys.getsizeof(data.ts) 
            self.bytes_written += sys.getsizeof(data.p1) 
            self.bytes_written += sys.getsizeof(data.p2) 


        log.info('{} bytes written to {}'.format(self.bytes_written, self.file.name))

    def close_file(self):
        if not self.file:
            return

        self.dump_to_file()

        if not self.file.closed:
            log.warning('closing file {}'.format(self.file.name))
            self.file.close()

        self.file = None
        

    def plot(self):
        if not self.dataqueue:
            log.warning('no data to plot')
            return
        t = []
        p = []

        for data in self.dataqueue:
            t.append(data.ts)
            p.append(data.p1)

        t = np.array(t)
        p = np.array(p)
        plt.plot(t - t[0], p, '-+')
        plt.show()


# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
class SerialThreadedReader(LineReader):
    on_connected_callback = None
    on_disconnected_callback = None
    on_data_callback = None

    def connection_made(self, transport):
        super(SerialThreadedReader, self).connection_made(transport)
        if self.on_connected_callback:
            self.on_connected_callback()

    def handle_line(self, line):
        ts = time.time()
        log.debug('line recieved:  {}'.format(line))
        values = re.split('[\\s,]+', line)
        if self.on_data_callback:
            p1 = float(values[1])
            p2 = 0.0
            if len(values) > 2:
                p2 = float(values[2])

            data = Packet(ts, p1, p2) 
            self.on_data_callback(data)


    def connection_lost(self, exc):
        if exc:
            print(exc)
        if self.on_disconnected_callback:
            self.on_disconnected_callback()

# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

@click.command(context_settings=CONTEXT_SETTINGS)
@click.option('-p', '--port',     default=None, help='serial port name')
@click.option('-b', '--baudrate', default=9600, help='set baud rate')
@click.option('-d', '--databits', default=8,    help='set databits')
@click.option(      '--parity',   default='N',  type=click.Choice(['N', 'E', 'O', 'S', 'M']), help='set parity')
@click.option('-s', '--stopbits', default=1,    help='set stop bits')
def main(port, baudrate, databits, parity, stopbits) -> int:

    ## ========================================================================
    ## set up logging from configuration file
    ## ========================================================================
    logging.config.fileConfig(
            'D:\\mensor\\.config\\logs.conf',
            disable_existing_loggers=False
            ) 

    aiolos_logging.change_all_logging_levels(logging.INFO)
    

    device = MensorCGP2300(
            port     = port,
            baudrate = baudrate,
            databits = databits,
            parity   = parity,
            stopbits = stopbits
            )


    while not device.connected and device.running:
        device.connect()
        if device.connected:
            device.runloop()

    return 0;

if __name__ == '__main__':
    sys.exit(main())
