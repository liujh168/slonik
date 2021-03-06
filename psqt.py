import bb
from side import *
from piece_type import *
from move_gen import *

pawn = [
      0,   0,   0,   0,   0,   0,   0,   0,
      0,   5,  10,  10,  10,  10,   5,   0,
    -16, -10,  15,  20,  20,   0,   0, -16,
    -20, -12,  20,  30,  30,  20, -12, -20,
    -20,   0,  10,  20,  20,  10,   0, -20,
    -12, -14,   3,  10,  10,   3, -14, -12,
    -10,  15,  -5,  -5,  -5,  -5,  15, -10,
      0,   0,   0,   0,   0,   0,   0,   0,
]

knight = [
    -80, -60, -60, -60, -60, -60, -60, -80,
    -60, -45, -25, -10, -10, -25, -45, -60,
    -20,   5,   5,  15,  15,   5,   5, -20,
    -20,   0,  25,  45,  45,  25,   0, -20,
    -20,   5,  20,  45,  45,  20,   5, -20,
    -20,  20,  35,  50,  50,  35,  20, -20,
    -80, -25,   5,  20,  20,   5, -25, -80,
   -100, -35, -25, -25, -25, -25, -35, -100,
]

bishop = [
    -25, -25, -25, -25, -25, -25, -25, -25,
    -20,  10,   5, -10, -10,   5,  10, -20,
    -10,  15,  10,   5,   5,  10,  15, -10,
     -5,  20,  10,   5,   5,  10,  20,  -5,
     -5,  10,   8,   5,   5,   8,  10,  -5,
     -5,   5,   5,  -8,  -8,   5,   5,  -5,
    -20,   5,  -5,   5,   5,  -5,   5, -20,
    -30, -20, -20, -20, -20, -20, -20, -30,
]

king = [
    -45, -45, -95, -95, -95, -95, -45, -45,
    -45, -45, -95, -95, -95, -95, -45, -45,
    -45, -45, -95, -95, -95, -95, -45, -45,
    -45, -45, -95, -95, -95, -95, -45, -45,
    -45, -45, -95, -95, -95, -95, -45, -45,
    -30, -35, -40, -45, -45, -40, -35, -30,
    -15, -15, -25, -20, -20, -25, -15, -15,
     20,  50,   0,  -5,  -5,   0,  50,  20,
]

def ind_for_square(square, side):
    bit_pos = bb.bit_position(square)
    col = bit_pos % 8
    row = bit_pos // 8
    if side == Side.WHITE:
        return 8 * (7-row) + (7-col)
    else:
        return 8 * row + col

def psqt_value_sq(piece, square, side):
    val = 0
    piece = PieceType.base_type(piece)
    if piece == PieceType.P:
        val = pawn[ind_for_square(square, side)]
    elif piece == PieceType.N:
        val = knight[ind_for_square(square, side)]
    elif piece == PieceType.B:
        val = bishop[ind_for_square(square, side)]
    else:
        return 5
    return val / 2
        
def psqt_value(piece, position, side):
    val = 0
    for sq in iterate_pieces(position.pieces[piece]):
        val += psqt_value_sq(piece, sq, side)
    return int(val)
