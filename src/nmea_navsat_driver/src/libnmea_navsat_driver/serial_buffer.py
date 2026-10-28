"""Frame serial chunks and retain the newest complete measurement of each type."""

from .checksum_utils import check_nmea_checksum


class NMEABuffer:
    def __init__(self):
        self.pending = b''

    def feed(self, chunk):
        lines = (self.pending + chunk).split(b'\n')
        # Bound memory if a disconnected/misconfigured device sends no newline.
        self.pending = lines.pop()[-65536:]
        newest = {}
        for index, line in enumerate(lines):
            # A reconnect can begin in the middle of binary or NMEA output.
            start = line.rfind(b'$')
            if start < 0:
                continue
            try:
                sentence = line[start:].strip().decode('ascii')
            except UnicodeDecodeError:
                continue
            if not check_nmea_checksum(sentence):
                continue
            identifier = sentence.split(',', 1)[0]
            if (len(identifier) != 6 or identifier[1:3] not in ('GP', 'GN', 'GL', 'IN')
                    or identifier[3:] not in ('GGA', 'RMC', 'GST', 'HDT', 'VTG')):
                continue
            # Retain order of the selected measurements, including GST before
            # GGA when the receiver emitted its uncertainty estimate first.
            newest[identifier[3:]] = (index, sentence)
        return [sentence for _, sentence in sorted(newest.values())]
