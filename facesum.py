#!/usr/bin/python2

import argparse, binascii, hashlib, math
import os, subprocess, sys, tempfile
import BaseHTTPServer

verbose = False

# simple slow naive implementation
class BitStream:
    def __init__(this, data, extend=False):
        this.data = []
        this.extend = extend
        for byte in data:
            byte = ord(byte)
            for bit in xrange(8):
                this.data.append(byte & 1)
                byte = byte >> 1

    def __len__(this):
        return len(this.data)

    def get(this, bitlen):
        value = this.data[:bitlen]
        ret = 0
        for bit in value:
            ret = (ret << 1) | bit
        this.data = this.data[bitlen:]
        if this.extend:
            this.data += value
        return ret
    
class MakeHumanFace:
    def __init__(this, path):
        this.path = path + '/makehuman'
        this.syspath = ['.' + x for x in ('/', '/lib', '/apps', '/shared', '/apps/gui', '/core', '/plugins')]

        #cwd = os.getcwd()
        #syspath = sys.path
        os.chdir(this.path)
        sys.path += this.syspath
    
        if verbose:
            sys.stderr.write("Probing makehuman ...\n")
    
        import core
        import headless
        import getpath
        import humanmodifier
        import log
        
        ## uncomment to disable makehuman log
        #log.init()
        
        #core.G.app = headless.ConsoleApp()
        #this.human = core.G.app.selectedHuman
        
        
        modifierGroups = ('head', 'forehead', 'eyebrows', 'neck', 'nose', 'mouth', 'ears', 'chin', 'cheek', 'macrodetails', 'macrodetails-universal', 'macrodetails-proportions')
        proxyTypes = ('hair', 'eyebrows', 'eyelashes')
        
        modifiers = humanmodifier.loadModifiers(getpath.getSysDataPath('modifiers/modeling_modifiers.json'), None)
        modifiers = [x for x in modifiers if x.groupName in modifierGroups and x.fullName != 'macrodetails/Caucasian']
        this.symmetricalModifiers = [x for x in modifiers if x.getSymmetrySide() is None]
        this.rightModifiers = [x for x in modifiers if x.getSymmetrySide() == 'r']
        this.leftModifiers = [x for x in modifiers if x.getSymmetrySide() == 'l']
        if verbose:
            sys.stderr.write("Found %i symmetrical facial features\n" % len(this.symmetricalModifiers))
            sys.stderr.write("Found %i left facial features\n" % len(this.leftModifiers))
            sys.stderr.write("Found %i right facial features\n" % len(this.rightModifiers))
        
        this.proxies = {}
        for proxyType in proxyTypes:
            files = getpath.search([getpath.getDataPath(proxyType),getpath.getSysDataPath(proxyType)], ['.proxy', '.mhclo'], True)
            files = list(files)
            if verbose:
                sys.stderr.write("Found %i %s proxies\n" % (len(files), proxyType))
            this.proxies[proxyType] = files
        
        skins = getpath.search([getpath.getDataPath('skins'),getpath.getSysDataPath('skins')], ['.mhmat'], True)
        this.skins = list(skins)
        if verbose:
            sys.stderr.write("Found %i skins\n" % len(this.skins))

    def makepng(this, data, symmetric=False, skin=False):
        os.chdir(this.path)

        import core
        import headless
        import humanargparser

        data = BitStream(data)
        if verbose:
            sys.stderr.write("%i bits of data input\n" % len(data))
        
        core.G.app = headless.ConsoleApp()
        human = core.G.app.selectedHuman
    

        ## extract enough bits to select proxies and materials
        
        proxies = {}
        for proxyType in this.proxies:
            proxyFiles = this.proxies[proxyType]
            nfiles = len(proxyFiles)
            bitlen = int(math.ceil(math.log(nfiles+1, 2)))
            fileIdx = int(round(data.get(bitlen) * nfiles / ((1<<bitlen)-1.0)))
            if (fileIdx == nfiles):
                if verbose:
                    sys.stderr.write("Selected no %s with %i bits\n" % (proxyType, bitlen))
            else:
                if verbose:
                    sys.stderr.write("Selected %s #%i with %i bits\n" % (proxyType, fileIdx, bitlen))
                proxies[proxyType] = proxyFiles[fileIdx]
        
        if skin:
            bitlen = int(math.ceil(math.log(len(this.skins), 2)))
            fileIdx = int(round(data.get(bitlen) * (len(this.skins)-1) / ((1<<bitlen)-1.0)))
            if verbose:
                sys.stderr.write("Selected skin #%i with %i bits\n" % (fileIdx, bitlen))
            skin = this.skins[fileIdx]
        
        proxies['eyes'] = 'data/eyes/high-poly/high-poly.mhclo'
        proxies['clothes'] = 'data/clothes/male_worksuit01/male_worksuit01.mhclo'
        
        
        ## spread remaining data among modifiers as floats
        
        if verbose:
            sys.stderr.write("%i bits remaining for facial features\n" % len(data))
        
        modifierDict = {}
        modifiers = this.symmetricalModifiers + this.leftModifiers
        if not symmetric:
            modifiers += this.rightModifiers
        modifierCount = len(modifiers)
        
        bitsPerModifier = len(data) / float(modifierCount)
        # some modifiers get one more bit than other modifiers
        detailedModifierCount = len(data) % modifierCount
        
        detailedAccumulated = 0
        for idx in xrange(modifierCount):
            if detailedAccumulated <  detailedModifierCount * idx / (modifierCount-1.0):
                bitlen = int(math.ceil(bitsPerModifier))
                detailedAccumulated = detailedAccumulated + 1
            else:
                bitlen = int(math.floor(bitsPerModifier))
            value = (data.get(bitlen) + 0.5) / (1<<bitlen)
            modifier = modifiers[idx]
            if verbose:
                sys.stderr.write("%s: %f with %i bits\n" % (modifier.fullName, value, bitlen))
            modifierDict[modifier.fullName] = value
            if symmetric and modifier.getSymmetrySide() is not None:
                modifierDict[modifier.getSymmetricOpposite()] = value

        modifierDict['macrodetails/Caucasian'] = 2.0 - modifierDict['macrodetails/African'] - modifierDict['macrodetails/Asian']
        
        
        ## generate human

        if verbose:
            sys.stderr.write("Generating human\n")
        
        humanargparser.mods_loaded = False
        humanargparser.applyModelingArguments(human, {
          'modifier' : modifierDict.iteritems(),
          'proxy' : proxies.iteritems(),
          'material' : None if skin == False else skin
        });
        
        
        ## render photo
        
        tempdir = tempfile.mkdtemp()
        objfile = tempfile.mkstemp(dir=tempdir)[1] + '.obj'
        outfile = tempfile.mkstemp(dir=tempdir)[1] + '.png'
        
        if verbose:
            sys.stderr.write("Rendering photo to %s\n" % outfile)
        
        headless.save(human, objfile)
        os.chdir(os.path.dirname(outfile))
        stdout, nothing = subprocess.Popen(['blender', realpath + '/photo.blend', '--background', '--render-output', outfile, '--python', realpath + '/blender_photo.py', '--', objfile], stdout=subprocess.PIPE).communicate()
        #os.system("blender '%s' --verbose 0 --background --render-output '%s' --python '%s' -- '%s'" % (realpath + "/photo.blend", outfile, realpath + "/blender_photo.py", objfile))
        with open(outfile, 'r') as outdata:
            photo = outdata.read()
        os.system("rm -rf %s" % tempdir)

        return photo

    

## prep arg parser

parser = argparse.ArgumentParser(description='Turn a short bit of data into an image of a human face.')

parser.add_argument('-m', '--makehuman', metavar='MAKEHUMAN-COMMANDLINE-PATH', required=True, help='path to makehuman-commandline sources')

parser.add_argument('-v', '--verbose', action='store_true')
parser.add_argument('-s', '--symmetric', action='store_true', help='only generate symmetric faces')
parser.add_argument('-k', '--skin', action='store_true', help='choose skin from data (default: strongest ethnicity)')
parser.add_argument('--fmt', choices=('hex','bin'), default='hex', help='parse hexadecimal or raw binary data (default: hex)')

outputgroup = parser.add_mutually_exclusive_group()
outputgroup.add_argument('-l', '--listen', nargs=2, metavar=('IP','PORT'), help='respond to HTTP POST data with face images, -o is ignored')
outputgroup.add_argument('-i', '--infile', default=sys.stdin, type=argparse.FileType('r'), help='file to read data from (default: stdin)')
outputgroup.add_argument('-d', '--data', help='data to read from command line')

parser.add_argument('-o', '--outfile', default=sys.stdout, type=argparse.FileType('w'), help='file to write data to (default: stdout)')

## process args

args = parser.parse_args()
fmt = args.fmt
symmetric = args.symmetric
skin = args.skin
verbose = args.verbose
realpath = os.path.dirname(os.path.realpath(sys.argv[0]))
mhf = MakeHumanFace(args.makehuman)

class HTTPRequestHandler(BaseHTTPServer.BaseHTTPRequestHandler):

    def do_POST(this):
        data = this.rfile.read(int(this.headers.getheader('content-length')))
        if fmt == 'hex':
            data = binascii.unhexlify(''.join(data.split()))
            
        png = mhf.makepng(data, symmetric, skin)
        this.send_response(200)
        this.send_header('Content-Type', 'image/png')
        this.end_headers()
        this.wfile.write(png)

if args.data is not None:
    data = args.data
elif args.listen is not None:
    addr=(args.listen[0],int(args.listen[1]))
    if verbose:
        sys.stderr.write("Listening on %s:%i\n" % addr)
    server = BaseHTTPServer.HTTPServer(addr, HTTPRequestHandler)
    server.serve_forever()
elif args.infile is not None:
    data = args.infile.read()

if fmt == 'hex':
    data = binascii.unhexlify(''.join(data.split()))


## output photo

args.outfile.write(mhf.makepng(data, symmetric, skin))

if verbose:
    sys.stderr.write("Data written to %s\n" % args.outfile.name)
    
    
