from IPython import embed
from evals import lowest_attacker, BaseEvaluator
from side import Side
from piece_type import PieceType as Pt
from bb import *
import numpy as np


LEFT_SIDE = FILES[0]|FILES[1]|FILES[2]|FILES[3]

def normalize_coord(x):
    return x / 8

class ToFeature():
    def __init__(self, position=None):
        if position:
            self.set_position(position)
        else:
            self.pos = None
            self.base_evaluator = None
        
    def set_position(self, position):
        self.pos = position
        self.base_evaluator = BaseEvaluator(position)
        
    def ann_features(self):
        # neural net features
        g = [] # global
        g.extend(self.side_to_move())
        g.extend(self.castling())
        g.extend(self.in_check())
        # g.extend(self.clock())
        # redundant with np but doing it anyway
        g.extend(self.king(Side.WHITE)) 
        g.extend(self.king(Side.BLACK)) 
    
        p = [] # pawn-centric
        nonp = [] # piece-centric
        s = [] # square-centric
        for side in [Side.W, Side.B]:
            g.extend(self.counts_and_values(side))
            
            p.extend(self.pawn_exists(side))
            p.extend(self.pawn_count(side))

            for bt in [Pt.N, Pt.B, Pt.R]:
                nonp.extend(self.BRN_pairs(bt, side))
            nonp.extend(self.queens(side))
            nonp.extend(self.king(side))

            for bt in Pt.piece_types(base_only=True):
                if bt != Pt.P:
                    s.extend(self.mobility(bt, side))
            s.extend(self.lowest_attacker(side))
        return [np.array(g), np.array(p), np.array(nonp), np.array(s)]
            
    def sq(self, sq, stm):
        x = get_file(sq) if sq else -1
        y = get_rank(sq) if sq else -1
        y_alt = get_rank(sq, stm) if sq else -1
        return [normalize_coord(c+1) for c in [x, y, y_alt]]

    def clock(self):
        return [self.pos.halfmove_clock / 50]
    
    def counts_and_values(self, side):
        f = []
        max_counts = [0] + [8,2,2,2,1,0]
        values = [0] + [1, 3.25, 3.25, 5, 9.75, 0]
        non_pawn_sum = 0
        pawn_sum = 0
        for pt in Pt.piece_types(side=side):
            bt = Pt.base_type(pt)
            if bt == Pt.K:
                continue
            count = count_bits(self.pos.pieces[pt])
            f.append(count / max_counts[bt])
            if bt == Pt.P:
                pawn_sum += count * values[bt]
            else:
                non_pawn_sum += count * values[bt]
        npv = non_pawn_sum / (2 * values[Pt.N] + 2 * values[Pt.B] + 2 * values[Pt.R] + values[Pt.Q])
        f.append(npv)
        pv = pawn_sum / (8 * values[Pt.P])
        f.append(pv)
        return f
    
    def side_to_move(self):
        return [int(self.pos.side_to_move() == Side.WHITE)]

    def in_check(self):
        return [int(self.pos.in_check())]
        
    def lowest_attacker(self, side): 
        f = []
        for sqind in range(64):
            sq = 1 << sqind
            lowest = Pt.NULL
            pieces = [Pt.P, Pt.N, Pt.B, Pt.R, Pt.Q, Pt.K]
            if self.base_evaluator.all_attacks[side]:
                lowest = pieces[-1] + 1
                for bt in pieces:
                    pt = Pt.piece(bt, side)
                    if self.base_evaluator.piece_attacks[pt] & sq:
                        lowest = bt
                        break
            f.append((7 - lowest) / 6) # lower pt gives higher "score"
        return f
    
    def castling(self):
        # castling rights preserved
        flags = self.pos.position_flags
        w00 = not (flags & 5)
        w000 = not (flags & 9)
        b00 = not (flags & 0x12)
        b000 = not (flags & 0x22)
        return [int(b) for b in [w00, w000, b00, b000]]

    def mobility(self, bt, stm):
        # attacks count, safe attacks count
        pos = self.pos
        pt = Pt.piece(bt, stm)
        attacks = self.base_evaluator.piece_attacks[pt]
        safe_attacks = self.base_evaluator.safe_attacks(bt, stm)
        return [count_bits(attacks) / 16, count_bits(safe_attacks) / 16]
        
    def queens(self, side):
        # coords, count
        queen_t = Pt.piece(Pt.Q, side)
        queens = self.pos.pieces[queen_t]
        f = self.sq(ls1b(queens), side)
        f.extend([count_bits(queens)])
        return f

    def king(self, side):
        # coords
        king_t = Pt.piece(Pt.K, side)
        k = self.pos.pieces[king_t]
        return self.sq(k, side)
    
    def BRN_pairs(self, bt, side):
        # B R and N pairs
        # ordered exist flags, coords, count
        pt = Pt.piece(bt, side)
        b = self.pos.pieces[pt]
        features = self.get_pairs(bt, side)
        features.extend([count_bits(b)])
        return features
    
    def get_pairs(self, bt, side):
        # exist 1, exist 2, 1 coords, 2 coords
        pos = self.pos
        pt = Pt.piece(bt, side)
        features = []
        b = pos.pieces[pt]
        count = count_bits(b)
        if count == 1:
            if b & LEFT_SIDE:
                features.extend([1,0])
                features.extend(self.sq(b, side))
                features.extend(self.sq(0, side))
            else:
                features.extend([0,1])
                features.extend(self.sq(0, side))
                features.extend(self.sq(b, side))
        elif count >= 2:
            features.extend([1,1])
            features.extend(self.sq(ls1b(b), side))
            b = reset_ls1b(b)
            features.extend(self.sq(ls1b(b), side))
        else:
            features.extend([0,0])
            features.extend(self.sq(0, side))
            features.extend(self.sq(0, side))
        return features

    def pawn_exists(self, side):
        # Double pawns disappear but hopefully the counts make up for it
        # I'd think this is better than filling in empty slots
        pos = self.pos
        pt = Pt.piece(Pt.P, side)
        features = [0] * 8
        pawns = pos.pieces[pt]
        for p in iterate_pieces(pawns):
            features[get_file(p)] = 1
        return features

    def pawn_count(self, side):
        pt = Pt.piece(Pt.P, side)
        return [count_bits(self.pos.pieces[pt]) / 8]
