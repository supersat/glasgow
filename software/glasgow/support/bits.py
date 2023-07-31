import re
import itertools
import operator
from collections.abc import Sequence, MutableSequence, Iterable

__all__ = ["bits", "bitarray"]

def _byte_len(l):
    return (l + 7) // 8

_byterev_lut = bytes(
    sum(
        ((byte >> bit) & 1) << (7 - bit)
        for bit in range(8)
    )
    for byte in range(0x100)
)

class _bits_base(Sequence):
    __slots__ = ("_len", "_bytes")

    @classmethod
    def from_int(cls, value, length=None):
        """Creates bits from an integer. If ``length`` is given, the integer will be
        masked to the target width. Otherwise, the smallest possible width will be
        used that does not mask off any bits of the integer, and the value must not
        be negative.
        """
        value = operator.index(value)
        if length is None:
            if value < 0:
                raise ValueError(f"invalid negative input for {cls.__name__}(): '{value}'")
            length = value.bit_length()
        else:
            length = operator.index(length)
            value &= ~(-1 << length)
        inst = object.__new__(cls)
        inst._len = length
        inst._bytes = cls._bytestype(value.to_bytes(_byte_len(length), 'little'))
        return inst

    @classmethod
    def from_str(cls, value):
        """Creates bits from a string. Any whitespace or ``_`` characters in the string
        will be discarded. The string must consist only of ``0`` and ``1`` characters.
        """
        value  = re.sub(r"[\s_]", "", value)
        if not re.match(r"^[01]*$", value):
            raise ValueError(f"invalid input for {cls.__name__}(): '{value}'")
        return cls.from_iter(int(x) for x in reversed(value))

    @classmethod
    def from_iter(cls, iterator):
        nbits = 0

        def make_bytes():
            nonlocal nbits
            byte = 0
            for bit in iterator:
                bit = operator.index(bit)
                if bit not in (0, 1):
                    raise ValueError(f"{cls.__name__} can only contain 0 and 1")
                byte |= bit << (nbits % 8)
                nbits += 1
                if nbits % 8 == 0:
                    yield byte
                    byte = 0
            if nbits % 8 != 0:
                yield byte
            return

        res = object.__new__(cls)
        res._bytes = cls._bytestype(make_bytes())
        res._len = nbits
        return res

    @classmethod
    def from_bytes(cls, value, length=None):
        value = cls._bytestype(value)
        if length is None:
            length = len(value) * 8
        if len(value) != _byte_len(length):
            raise ValueError(f"wrong bytes length {len(value)} for {cls.__name__} of length {length}")
        if length % 8:
            mask = -1 << (length % 8)
            if value[-1] & (-1 << (length % 8)):
                raise ValueError("wrong padding in the last byte")
        res = object.__new__(cls)
        res._bytes = value
        res._len = length
        return res

    def __new__(cls, value=0, length=None):
        if isinstance(value, _bits_base):
            if length is not None:
                raise ValueError(f"invalid input for {cls.__name__}(): when converting from bits "
                                 "length must not be provided")
            if cls is bits and type(value) is bits:
                return value
            res = object.__new__(cls)
            res._bytes = cls._bytestype(value._bytes)
            res._len = value._len
            return res
        if isinstance(value, int):
            return cls.from_int(value, length)
        if isinstance(value, str):
            if length is not None:
                raise ValueError(f"invalid input for {cls.__name__}(): when converting from str "
                                 "length must not be provided")
            return cls.from_str(value)
        if isinstance(value, (bytes, bytearray, memoryview)):
            return cls.from_bytes(value, length)
        if isinstance(value, Iterable):
            if length is not None:
                raise ValueError(f"invalid input for {cls.__name__}(): when converting from an iterable "
                                 "length must not be provided")
            return cls.from_iter(value)
        raise TypeError(f"invalid input for {cls.__name__}(): cannot convert from {value.__class__.__name__}")

    def __len__(self):
        return self._len

    def __bool__(self):
        return bool(self._len)

    def __eq__(self, other):
        if not isinstance(other, _bits_base):
            return False
        return self._len == other._len and self._bytes == other._bytes

    def __getitem__(self, key):
        if isinstance(key, slice):
            start, stop, step = key.indices(self._len)
            if not range(start, stop, step):
                # get empty slices out of the way first
                return self.__class__()
            elif step == -1 and start % 8 == 7 and stop % 8 == 7:
                # byte-aligned reverse fastpath
                res = object.__new__(self.__class__)
                res._bytes = self._bytes[start // 8 : stop // 8 : -1].translate(_byterev_lut)
                res._len = start - stop
                return res
            elif step == 1 and start % 8 == 0 and (stop % 8 == 0 or stop == self._len):
                # byte-aligned normal fastpath (stop either byte-aligned,
                # or matches end of sequence)
                res = object.__new__(self.__class__)
                res._bytes = self._bytes[start // 8 : (stop + 7) // 8]
                res._len = stop - start
                return res
            else:
                # slow path
                return self.from_iter(self[i] for i in range(start, stop))
        else:
            try:
                key = operator.index(key)
            except:
                raise TypeError(f"{self.__class__.__name__} indices must be integers or slices, not {key.__class__.__name__}")
            if key < 0:
                key += self._len
            if key not in range(self._len):
                raise IndexError(f"{self.__class__.__name__} index out of range")
            return (self._bytes[key // 8] >> (key % 8)) & 1

    def to_int(self):
        return int.from_bytes(self._bytes, 'little')

    def to_str(self):
        return ''.join(str(x) for x in reversed(self))

    def to_bytes(self):
        return bytes(self._bytes)

    __int__ = to_int
    __str__ = to_str
    __bytes__ = to_bytes

    def __repr__(self):
        return f"{self.__class__.__name__}('{self}')"

    def __add__(self, other):
        if isinstance(other, (str, Iterable)):
            other = bits(other)
        elif not isinstance(other, _bits_base):
            return NotImplemented
        if self._len % 8 == 0:
            res = object.__new__(self.__class__)
            res._bytes = self._bytes + other._bytes
            res._len = self._len + other._len
            return res
        return self.from_iter(itertools.chain(self, other))

    def __radd__(self, other):
        if isinstance(other, (str, Iterable)):
            other = bits(other)
        elif not isinstance(other, _bits_base):
            return NotImplemented
        if other._len % 8 == 0:
            res = object.__new__(self.__class__)
            res._bytes = other._bytes + self._bytes
            res._len = other._len + self._len
            return res
        return self.from_iter(itertools.chain(other, self))

    def __mul__(self, other):
        if not isinstance(other, int):
            return NotImplemented
        if self._len % 8 == 0:
            res = object.__new__(self.__class__)
            res._bytes = self._bytes * other
            res._len = self._len * other
            return res
        return self.from_iter(itertools.chain.from_iterable(itertools.repeat(self, other)))

    __rmul__ = __mul__

    def _bitop(self, other, op):
        if isinstance(other, int):
            other = bits(other, self._len)
        elif not isinstance(other, _bits_base):
            other = bits(other)
        if len(other) != len(self):
            raise ValueError("mismatched bitwise operator widths")
        res = object.__new__(self.__class__)
        res._bytes = self._bytestype(op(a, b) for (a, b) in zip(self._bytes, other._bytes))
        res._len = self._len
        return res

    def __and__(self, other):
        return self._bitop(other, operator.__and__)

    __rand__ = __and__

    def __or__(self, other):
        return self._bitop(other, operator.__or__)

    __ror__ = __or__

    def __xor__(self, other):
        return self._bitop(other, operator.__xor__)

    __rxor__ = __xor__

    def __not__(self):
        if self._len % 8 == 0:
            pad_idx = None
        else:
            pad_idx = self._len // 8
            pad_mask = ~(-1 << self._len % 8)
        res = object.__new__(self.__class__)
        res._bytes = self._bytestype(
            ~x & pad_mask if i == pad_idx else ~x
            for i, x in self._bytes
        )
        res._len = self._len
        return res

    def reversed(self):
        if self._len % 8 == 0:
            res = object.__new__(self.__class__)
            res._bytes = self._bytes.translate(_byterev_lut)[::-1]
            res._len = self._len
            return res
        else:
            return self.from_iter(reversed(self))

    def byte_reversed(self):
        if self._len % 8 == 0:
            res = object.__new__(self.__class__)
            res._bytes = self._bytes.translate(_byterev_lut)
            res._len = self._len
            return res
        else:
            raise ValueError(f"byte_reversed requires {self.__class__.__name__} of length divisible by 8")

    def find(self, sub, start=0, end=None):
        if isinstance(sub, (str, Iterable)):
            sub = bits(sub)
        elif not isinstance(sub, _bits_base):
            sub = bits([sub])
        if end is None:
            end = self._len
        end = min(end, self._len - (sub._len - 1))
        for i in range(start, end):
            if all(self[i + j] == sub[j] for j in range(sub._len)):
               return i
        return -1

    def index(self, *args, **kwargs):
        res = self.find(*args, **kwargs)
        if res == -1:
            raise ValueError("substring not found")
        return res


class bits(_bits_base):
    """An immutable bit sequence, like ``bytes`` but for bits.

    This bit sequence is ordered from LSB to MSB; this is the direction in which it is converted
    to and from iterators, and to and from bytes. Note, however, that it is converted to and from
    strings (which should be only used where a human-readable form is required) from MSB to LSB;
    this matches the way integer literals are written, as well as values in datasheets and other
    documentation.
    """

    __slots__ = ()
    _bytestype = bytes

    def __hash__(self):
        return hash((self._len, self._bytes))

class bitarray(_bits_base, MutableSequence):
    """A mutable bit sequence, like ``bytearray`` but for bits.

    Works like ``bits``, but has additional mutation methods and cannot be hashed.
    """

    __slots__ = ()
    _bytestype = bytearray

    def _fix_padding(self):
        if self._len % 8 != 0:
            self._bytes[-1] &= ~(-1 << (self._len % 8))

    def _resize(self, length):
        blen = _byte_len(length)
        if length < self._len:
            del self._bytes[blen:]
            self._fix_padding()
        elif length > self._len:
            self._bytes += bytes(blen - self._bytes)
        self._len = length

    def __setitem__(self, key, value):
        if isinstance(key, slice):
            start, stop, step = key.indices(self._len)
            if isinstance(value, int):
                value = bits(value, len(range(start, stop, step)))
            elif isinstance(value, str):
                value = bits(value)
            elif not isinstance(value, _bits_base):
                raise ValueError("invalid type for bitarray slice assignment")
            rng = range(start, stop, step)
            if step != 1:
                # generic slow path
                if len(rng) != len(value):
                    raise ValueError(f"atempt to assign sequence of size {len(value)} to extended slice of size {len(rng)}")
                for di, bit in zip(rng, value):
                    self[di] = bit
            elif start % 8 == 0 and stop % 8 == 0 and value._len % 8 == 0:
                # byte-aligned fastpath with aligned ends
                self._bytes[start // 8 : stop // 8] = value._bytes
                self._len = len(self._bytes) * 8
            elif start % 8 == 0 and stop == self._len:
                # byte-aligned fastpath with no tail
                self._bytes[start // 8 :] = value._bytes
                self._len = start + value._len
            elif stop - start == value._len:
                # slow-ish path, no resize
                for di, bit in zip(rng, value):
                    self[di] = bit
            elif stop == self._len:
                # slow-ish path, extend
                self._resize(self._len + value._len)
                for di, bit in zip(rng, value):
                    self[di] = bit
            else:
                # slow path
                tail = self[stop:]
                self._resize(start)
                self += value
                self += tail
        else:
            try:
                key = operator.index(key)
            except:
                raise TypeError(f"{self.__class__.__name__} indices must be integers or slices, not {key.__class__.__name__}")
            value = operator.index(value)
            if value not in (0, 1):
                raise ValueError("bit value must be 0 or 1")
            if key < 0:
                key += self._len
            if key not in range(self._len):
                raise IndexError("bits index out of range")
            if value:
                self._bytes[key // 8] |= 1 << (key % 8)
            else:
                self._bytes[key // 8] &= ~(1 << (key % 8))

    def __delitem__(self, key, value):
        if isinstance(key, slice):
            start, stop, step = key.indices(self._len)
            if not range(start, stop, step):
                # get empty slices out of the way first
                return
            elif step == 1 and start % 8 == 0 and (stop % 8 == 0 or stop == self._len):
                # byte-aligned normal fastpath (stop either byte-aligned,
                # or matches end of sequence)
                if stop == self._len:
                    self._len = start
                else:
                    self._len -= stop - start
                del self._bytes[start // 8 : (stop + 7) // 8]
                return res
            elif step == 1 and stop == self._len:
                # simple trim
                self._resize(start)
            elif step == 1:
                # slow path
                tail = self[stop:]
                self._resize(start)
                self += tail
            else:
                # insane slow path
                res = self.from_iter(
                    x
                    for (i, x) in enumerate(self)
                    if i not in range(start, stop, step)
                )
                self._bytes = res._bytes
                self._len = res._len
        else:
            try:
                key = operator.index(key)
            except:
                raise TypeError(f"{self.__class__.__name__} indices must be integers or slices, not {key.__class__.__name__}")
            if key < 0:
                key += self._len
            if key not in range(self._len):
                raise IndexError("bits index out of range")
            del self[key:key+1]

    def insert(self, index, value):
        index = operator.index(index)
        value = operator.index(value)
        if value not in (0, 1):
            raise ValueError("wrong value for bitarray")
        if index < 0:
            index += self._len
        if index == self._len:
            if self._len % 8 == 0:
                self._bytes.append(0)
            self._len += 1
            self[index] = value
        else:
            self[index:index] = bits(value, 1)

    def clear(self):
        self._bytes.clear()
        self._len = 0

    def reverse(self):
        if self._len % 8 == 0:
            self._bytes = self._bytes.translate(_byterev_lut)
            self._bytes.reverse()
        else:
            super().reverse()

    def reverse(self):
        if self._len % 8 == 0:
            self._bytes = self._bytes.translate(_byterev_lut)
        else:
            raise ValueError("byte_reverse requires a bitstream of length divisible by 8")

    def extend(self, values):
        if isinstance(values, (str, _bits_base)):
            self[self._len:] = values
        else:
            super().extend(values)

    def __imul__(self, other):
        other = operator.index(other)
        if self._len % 8 == 0 or other == 0:
            self._bytes *= other
            self._len *= other
        elif other < 0:
            raise ValueError("cannot multiply bitarray by negative count")
        elif other != 1:
            val = self[:]
            for _ in range(other - 1):
                self += val

    def _ibitop(self, other, op):
        if isinstance(other, int):
            other = bits(other, self._len)
        elif not isinstance(other, _bits_base):
            other = bits(other)
        if len(other) != len(self):
            raise ValueError("mismatched bitwise operator widths")
        for i, b in enumerate(other._bytes):
            self._bytes[i] = op(self._bytes[i], b)

    def __iand__(self, other):
        self._ibitop(other, operator.__and__)
        return self

    def __ior__(self, other):
        self._ibitop(other, operator.__or__)
        return self

    def __ixor__(self, other):
        self._ibitop(other, operator.__xor__)
        return self

    def setall(self, value):
        value = operator.index(value)
        if value not in (0, 1):
            raise ValueError("bit value must be 0 or 1")
        if value:
            self._bytes = bytearray(b"\xff" * len(self._bytes))
            self._fix_padding()
        else:
            self._bytes = bytearray(len(self._bytes))


# -------------------------------------------------------------------------------------------------

import unittest


class BitsTestCase(unittest.TestCase):
    def assertBits(self, value, bit_length, bit_value):
        self.assertIsInstance(value, bits)
        self.assertEqual(value._len, bit_length)
        self.assertEqual(value._bytes, bit_value.to_bytes(_byte_len(bit_length), 'little'))

    def test_from_int(self):
        self.assertBits(bits.from_int(0), 0, 0b0)
        self.assertBits(bits.from_int(1), 1, 0b1)
        self.assertBits(bits.from_int(2), 2, 0b10)
        self.assertBits(bits.from_int(2, 5), 5, 0b00010)
        self.assertBits(bits.from_int(0b110, 2), 2, 0b10)
        self.assertBits(bits.from_int(-1, 16), 16, 0xffff)

    def test_from_int_wrong(self):
        with self.assertRaisesRegex(ValueError,
                r"invalid negative input for bits\(\): '-1'"):
            bits.from_int(-1)

    def test_from_str(self):
        self.assertBits(bits.from_str(""), 0, 0b0)
        self.assertBits(bits.from_str("0"), 1, 0b0)
        self.assertBits(bits.from_str("010"), 3, 0b010)
        self.assertBits(bits.from_str("0 1  011_100"), 8, 0b01011100)
        self.assertBits(bits.from_str("0 1 \t011_100"), 8, 0b01011100)

    def test_from_str_wrong(self):
        with self.assertRaisesRegex(ValueError,
                r"invalid input for bits\(\): '-1'"):
            bits.from_str("-1")
        with self.assertRaisesRegex(ValueError,
                r"invalid input for bits\(\): '23'"):
            bits.from_str("23")

    def test_from_bytes(self):
        self.assertBits(bits.from_bytes(b"\xa5", 8), 8, 0b10100101)
        self.assertBits(bits.from_bytes(b"\xa5\x01", 9), 9, 0b110100101)

    def test_from_bytes_wrong(self):
        with self.assertRaisesRegex(ValueError,
                r"wrong padding in the last byte"):
            bits.from_bytes(b"\xa5\xff", 9)
        with self.assertRaisesRegex(ValueError,
                r"wrong bytes length 2 for bits of length 20"):
            bits.from_bytes(b"\xa5\xff", 20)

    def test_from_iter(self):
        self.assertBits(bits.from_iter(iter([])), 0, 0b0)
        self.assertBits(bits.from_iter(iter([1,1,0,1,0,0,1])), 7, 0b1001011)

    def test_new(self):
        self.assertBits(bits(), 0, 0b0)
        self.assertBits(bits(10), 4, 0b1010)
        self.assertBits(bits(10, 2), 2, 0b10)
        self.assertBits(bits("1001"), 4, 0b1001)
        self.assertBits(bits(b"\xa5\x01", 9), 9, 0b110100101)
        self.assertBits(bits(bytearray(b"\xa5\x01"), 9), 9, 0b110100101)
        self.assertBits(bits(memoryview(b"\xa5\x01"), 9), 9, 0b110100101)
        self.assertBits(bits(b"\xa5\x01"), 16, 0b0000000110100101)
        self.assertBits(bits([1,1,0,1,0,0,1]), 7, 0b1001011)
        some = bits("1001")
        self.assertIs(bits(some), some)

    def test_new_wrong(self):
        with self.assertRaisesRegex(TypeError,
                r"invalid input for bits\(\): cannot convert from float"):
            bits(1.0)
        with self.assertRaisesRegex(ValueError,
                r"invalid input for bits\(\): when converting from str "
                r"length must not be provided"):
            bits("1010", 5)
        with self.assertRaisesRegex(ValueError,
                r"invalid input for bits\(\): when converting from an iterable "
                r"length must not be provided"):
            bits([1,0,1,0], 5)

    def test_len(self):
        self.assertEqual(len(bits(10)), 4)

    def test_bool(self):
        self.assertFalse(bits(""))
        self.assertTrue(bits("1"))
        self.assertTrue(bits("01"))
        self.assertTrue(bits("0"))
        self.assertTrue(bits("00"))

    def test_int(self):
        self.assertEqual(int(bits("1010")), 0b1010)

    def test_str(self):
        self.assertEqual(str(bits("")), "")
        self.assertEqual(str(bits("0000")), "0000")
        self.assertEqual(str(bits("1010")), "1010")
        self.assertEqual(str(bits("01010")), "01010")

    def test_bytes(self):
        self.assertEqual(bytes(bits("")), b"")
        self.assertEqual(bytes(bits("10100101")), b"\xa5")
        self.assertEqual(bytes(bits("110100101")), b"\xa5\x01")

    def test_repr(self):
        self.assertEqual(repr(bits("")), r"bits('')")
        self.assertEqual(repr(bits("1010")), r"bits('1010')")

    def test_getitem_int(self):
        some = bits("10001001011")
        self.assertEqual(some[0], 1)
        self.assertEqual(some[2], 0)
        self.assertEqual(some[5], 0)
        self.assertEqual(some[-1], 1)
        self.assertEqual(some[-2], 0)
        self.assertEqual(some[-5], 1)

    def test_getitem_slice(self):
        some = bits("10001001011")
        self.assertBits(some[:], 11, 0b10001001011)
        self.assertBits(some[2:], 9, 0b100010010)
        self.assertBits(some[2:9], 7, 0b0010010)
        self.assertBits(some[2:-2], 7, 0b0010010)
        self.assertBits(some[3:2], 0, 0b0)

    def test_getitem_wrong(self):
        with self.assertRaisesRegex(TypeError,
                r"bits indices must be integers or slices, not str"):
            bits()["x"]

    def test_iter(self):
        some = bits("10001001011")
        self.assertEqual(list(some), [1,1,0,1,0,0,1,0,0,0,1])

    def test_eq(self):
        self.assertEqual(bits("1010"), bits("1010"))
        self.assertNotEqual(bits("1010"), 0b1010)
        self.assertNotEqual(bits("1010"), "1010")
        self.assertNotEqual(bits("1010"), bits("01010"))
        self.assertNotEqual(bits("1010"), None)

    def test_add(self):
        self.assertBits(bits("1010") + bits("1110"), 8, 0b11101010)
        self.assertBits(bits("1010") + (0,1,1,1), 8, 0b11101010)
        self.assertBits((0,1,1,1) + bits("1010"), 8, 0b10101110)

    def test_mul(self):
        self.assertBits(bits("1011") * 4, 16, 0b1011101110111011)
        self.assertBits(4 * bits("1011"), 16, 0b1011101110111011)

    def test_and(self):
        self.assertBits(bits("1010") & bits("1100"), 4, 0b1000)
        self.assertBits(bits("1010") & "1100", 4, 0b1000)
        self.assertBits((0,1,0,1) & bits("1100"), 4, 0b1000)

    def test_or(self):
        self.assertBits(bits("1010") | bits("1100"), 4, 0b1110)
        self.assertBits(bits("1010") | "1100", 4, 0b1110)
        self.assertBits((0,1,0,1) | bits("1100"), 4, 0b1110)

    def test_xor(self):
        self.assertBits(bits("1010") ^ bits("1100"), 4, 0b0110)
        self.assertBits(bits("1010") ^ "1100", 4, 0b0110)
        self.assertBits((0,1,0,1) ^ bits("1100"), 4, 0b0110)

    def test_reversed(self):
        self.assertBits(bits("1010").reversed(), 4, 0b0101)

    def test_find(self):
        self.assertEqual(bits("1011").find(bits("11")), 0)
        self.assertEqual(bits("1011").find(bits("10")), 2)
        self.assertEqual(bits("1011").find(bits("01")), 1)
        self.assertEqual(bits("1011").find(bits("00")), -1)

        self.assertEqual(bits("101100101").find(bits("10"), 0), 1)
        self.assertEqual(bits("101100101").find(bits("10"), 2), 4)
        self.assertEqual(bits("101100101").find(bits("10"), 5), 7)
        self.assertEqual(bits("101100101").find(bits("10"), 8), -1)

        self.assertEqual(bits("1011").find(bits((1,0))), 1)
