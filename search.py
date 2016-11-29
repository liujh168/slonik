from IPython import embed
from collections import namedtuple
from position import *
from constants import *
from collections import defaultdict
from material import *
from psqt import *
# from evals import eval_see, rook_position_bonus, pawn_cover_bonus, king_safety_squares, king_zone_attack_bonus
from evals import *
from operator import itemgetter
import itertools
import tt

class SearchInfo():
    def __init__(self):
        self.ply = 0
        self.current_variation = []
        self.pv = []
        self.null_move_prune_search = False
        self.skip_early_pruning = False
        self.singular_search = False
        self.excluded_move = Move(PieceType.NULL)
        self.eval = 0

# history moves
History = namedtuple('History', ['move', 'value'])
move_history = [[[None for i in range(64)] for i in range(13)] for i in range(2)]
def update_history(side, move, value):
    entry = move_history[side][move.piece_type][bit_position(move.to_sq)]
    adjusted_val = value
    if entry:
        adjusted_val = entry.value + .2 * (value - entry.value)
    move_history[side][move.piece_type][bit_position(move.to_sq)] = History(move, adjusted_val)
def lookup_history(side, move):
    if move and move.piece_type is not PieceType.NULL:
        return move_history[side][move.piece_type][bit_position(move.to_sq)]
    
# counter moves
Counter = namedtuple('Counter', ['move'])
counter_history = [[[None for i in range(64)] for i in range(13)] for i in range(2)]
def update_counter(side, move, counter):
    entry = counter_history[side][move.piece_type][bit_position(move.to_sq)]
    counter_history[side][move.piece_type][bit_position(move.to_sq)] = Counter(counter)
def lookup_counter(side, move):
    if move and move.piece_type is not PieceType.NULL:
        return counter_history[side][move.piece_type][bit_position(move.to_sq)]
    
tb_hits = 0
node_count = 0
killer_moves = defaultdict(list)

ply_count = 0
ply_iter = 0
ply_max = 0
def update_ply_stat(ply):
    global ply_count
    global ply_iter
    global ply_max
    ply_count += ply
    ply_iter += 1
    if ply > ply_max: ply_max = ply
    
def add_killer(ply, move):
    if move in killer_moves[ply]:
        return
    if len(killer_moves[ply]) == 3:
        killer_moves[ply].pop()
    killer_moves[ply].append(move)

def depth_to_allowance(depth):
    return int(math.ceil(.193006 * math.e ** (1.29829 * depth)) + depth * 3)

def allowance_to_depth(allowance):
    return round(math.log(allowance / .193006) / 1.29829, 1)

def iterative_deepening(target_depth, node, si=None):
    alpha = LOW_BOUND
    beta = HIGH_BOUND

    depth = 0
    
    val = 0
    si = si or [None] * 64
    
    while depth < target_depth:
        depth += 1
        allowance = depth_to_allowance(depth)
        finished = False
        fail_factor = 18

        alpha, beta = val - fail_factor, val + fail_factor
        
        print ("\n>> depth:", depth, ", allowance:", allowance)
        
        while not finished:
            val = search(node, si, 0, alpha, beta, allowance, True, False)

            if val < alpha:
                print("faillow", "a", alpha, "b", beta, "val", val, "factor", fail_factor)
            if val > beta:
                print("failhigh", "a", alpha, "b", beta, "val", val, "factor", fail_factor)

            if val <= alpha:
                alpha = val - fail_factor
                # beta = (alpha + beta) // 2
                fail_factor += fail_factor // 3 + 6
            elif val >= beta:
                # alpha = (alpha + beta) / 2
                beta = val + fail_factor
                fail_factor += fail_factor // 3 + 6
            else:
                finished = True
    
    return val, si
    
def search(node, si, ply, a, b, allowance, pv_node, cut_node):
    global node_count
    global ply_iter
    global ply_count
    node_count += 1
    
    assert(pv_node or a == b-1)
    
    a_orig = a
    is_root = pv_node and ply == 0
    
    si[ply] = si[ply] or SearchInfo()
    si[ply+1] = si[ply+1] or SearchInfo()

    pos_key = node.zobrist_hash ^ si[ply].excluded_move.compact()
    
    found = False
    found, tt_ind, tt_entry = tt.get_tt_index(pos_key)
    if not pv_node and found and tt_entry.depth >= allowance:
        if (tt_entry.bound_type == tt.BoundType.LO_BOUND and tt_entry.value >= b) \
           or (tt_entry.bound_type == tt.BoundType.HI_BOUND and tt_entry.value < a) \
           or tt_entry.bound_type == tt.BoundType.EXACT:
            return tt_entry.value

    if found and tt_entry.static_eval is not None:
        si[ply].static_eval = static_eval = tt_entry.static_eval
    else:
        if node.last_move() == Move(PieceType.NULL):
            si[ply].static_eval = static_eval = -si[ply-1].static_eval + 40
        else:
            # if ' '.join(map(str,node.moves)) == "Rf1-e1 f7-f6":
            #     print("debug")
            si[ply].static_eval = static_eval = evaluate(node)
        tt.save_tt_entry(tt.TTEntry(pos_key, 0, tt.BoundType.NONE, 0, 0, static_eval))
        
    in_check = node.in_check()
        
    # if curr_p <= thres_p:
    if allowance <= 1:
        score = qsearch(node, si, ply, a, b, 9, pv_node, in_check)
        return score
    
    if not in_check:
        if not si[ply].skip_early_pruning:
            # futility prune of parent
            if allowance_to_depth(allowance) < 6 \
               and static_eval - allowance_to_depth(allowance) * 150 >= b:
                return static_eval
            
            # null move pruning.. if pass move and we're still failing high, dont bother searching further
            if not pv_node and not si[ply].null_move_prune_search \
               and found and tt_entry.value >= b:
                si[ply+1].null_move_prune_search = True
                node.toggle_side_to_move()
                val = -search(node, si, ply+1, -b, -b+1, int(allowance * .75), False, False)
                node.toggle_side_to_move()
                si[ply+1].null_move_prune_search = False

                if val >= b:
                    # print(" **** NULL BETA CUTTOFF after", ' '.join(map(str,node.moves)), "--winning for", node.side_to_move(), tt_entry.value, val, a, b)
                    return val

        # internal iterative deepening to improve move order when there's no pv
        if not found and allowance_to_depth(allowance) >= 4 \
           and (pv_node or static_eval + MG_PIECES[PieceType.P] >= b):
            si[ply+1].skip_early_pruning = True
            val = search(node, si, ply, a, b, int(allowance * .75), pv_node, cut_node)
            si[ply+1].skip_early_pruning = False
            found, tt_ind, tt_entry = tt.get_tt_index(node.zobrist_hash)
    
    singular_extension_eligible = False
    if not is_root and allowance_to_depth(allowance) >= 2.5 \
       and not si[ply].singular_search \
       and found \
       and tt_entry.move != 0 \
       and tt_entry.bound_type != tt.BoundType.HI_BOUND \
       and tt_entry.depth >= allowance * .7:
        # print("SINGULARELIGIBLE", ' '.join(map(str,node.moves)))
        singular_extension_eligible = True

    improving = ply < 2 or si[ply-2].static_eval is None or si[ply].static_eval >= si[ply-2].static_eval
        
    best_move = None
    best_move_is_capture = False
    best_val = LOW_BOUND
    move_count = 0

    # if ' '.join(map(str,node.moves)) == "Ng4-e5 Nf3-e5 Nc6-e5":
    #     print("debug")
    legal_moves = node.generate_moves()
    moves = sort_moves(legal_moves, node, si, ply, False)
    for move in moves:

        if improving:
            move.prob *= min(move.prob * 1.1, 1)
            
        # Ng4-e5 Nf3-e5 Nc6-e5 Rf1-e1
        if ' '.join(map(str,node.moves)) == "Ng4-e5 Nf3-e5 Nc6-e5" and str(move)=="Rf1-e1":
            print("debug")
        
        if si[ply].excluded_move == move:
            continue
        
        child = move.position
        move_count += 1
        
        is_capture = move.to_sq & node.occupied[child.side_to_move()]
        see_score = move.see_score or eval_see(node, move)
        gives_check = child.in_check()
    
        # singular extension logic pretty much as in stockfish
        if singular_extension_eligible and move == Move.move_uncompacted(tt_entry.move):
            # print("Trying Singular:", ' '.join(map(str,node.moves)), move)
            rbeta = tt_entry.value - (2 * allowance_to_depth(allowance))
            si[ply].excluded_move = move
            si[ply].singular_search = True
            si[ply].skip_early_pruning = True
            val = search(node, si, ply, rbeta-1, rbeta, int(allowance * move.prob * .75), False, cut_node)
            si[ply].skip_early_pruning = False
            si[ply].singular_search = False
            si[ply].excluded_move = Move(PieceType.NULL)
            # print("val", val, "rbeta", rbeta)
            
            if val < rbeta:
                print("singular extension worked for move", move, "in line", node.moves, "val w/o this move", val, "< rbeta", rbeta)
                move.prob = 1

        if not is_root and not is_capture and not gives_check:
            next_depth = allowance_to_depth(allowance * move.prob)
            if next_depth <= 5 and not in_check \
               and static_eval + .75 * MG_PIECES[PieceType.P] + next_depth * MG_PIECES[PieceType.P] <= a:
                continue
        
            # prune moves with too-negative SEE; more lenient with moves closer to root
            if next_depth < 8 and see_score <= -35 * next_depth ** 2:
                continue
        
        # TODO?: if non rootNode and we're losing, only look at checks/big captures >= alpha 
        
        # if lmr_depth < 3 and not is_capture:
        #     counter = lookup_counter(node.side_to_move(), move)
        #     history = lookup_history(node.side_to_move(), move)
        #     # TODO: check that counter is legal?
        #     if counter and history and history < -10:
        #         print("hist val", history, "cnter", counter.move, "pruning", move)
        #         continue
        #         # lmr_depth = max(lmr_depth - 1, 0)
        
        # Probabilistic version of LMR
        # .. zero window search reduced 
        zw_allowance = allowance * move.prob 
        if allowance_to_depth(allowance) >= 3 and not is_capture:
            r = min(zw_allowance * .25, depth_to_allowance(1))
            if cut_node:
                r += depth_to_allowance(2)
            else:
                child.toggle_side_to_move()
                undo_see = eval_see(child, Move(move.piece_type, move.to_sq, move.from_sq))
                child.toggle_side_to_move()
                if undo_see < 0:
                    # reduce reduction if escaping capture
                    r -= depth_to_allowance(2)
                else:
                    # reduce reduction if making a threat
                    ep_default_value = (0, 0, 0, 0)
                    victim_before, *rest = next(next_en_prise(node, child.side_to_move()), ep_default_value)
                    victim_after, *rest = next(next_en_prise(child, child.side_to_move()), ep_default_value)
                    if victim_after > victim_before:
                        r -= depth_to_allowance(2)

            hist = lookup_history(node.side_to_move(), move)
            if hist and hist.value > 0:
                r -= depth_to_allowance(1)
            elif hist and hist.value < 0:
                r += depth_to_allowance(1)

            if r < 0: r = 0

            val = -search(child, si, ply+1, -(a+1), -a, int(zw_allowance - r), False, True)
            do_full_zw = val > a and r != 0
        else:
            do_full_zw = not (pv_node and (move.prob >= .4))
        
        # .. zero window full allotment search
        if do_full_zw:
            val = -search(child, si, ply+1, -(a+1), -a, int(zw_allowance), True, not cut_node)
            
        # .. full window full allotment search
        # otherwise we let the fail highs cause parent to fail low and try different move
        if pv_node and (move.prob >= .4 or (a < val and (val < b or is_root))):
            val = -search(child, si, ply+1, -b, -a, int(allowance * move.prob), True, False)
            
        if val > best_val:
            # if ' '.join(map(str,node.moves)) == "Ng4-e5 Nf3-e5 Nc6-e5":
            #     print("VAL OF Ng4-e5 Nf3-e5 Nc6-e5:", val)
            best_val, best_move = val, move
            # if move_count > 5:
            #     print("movecount", move_count, move, list(map(str,node.moves)))
            best_move_is_capture = is_capture
            if val > a and pv_node:
                si[ply].pv = [move] + si[ply+1].pv
                si[ply+1].pv = []
                # si.pv = si.current_variation
                # si.pv = si.pv[:si.ply] + si.current_variation[si.ply:]
                if is_root:
                    print_moves(si[ply].pv)
                
        a = max(a, val)
        if a >= b:
            if best_move: 
                add_killer(ply, best_move)
            break

    prior_move = node.last_move()
    if len(moves) == 0:
        # mate or statemate
        if si[ply].excluded_move == Move(PieceType.NULL):
            best_val = a
        else:
            best_val = evaluate(node)
    elif best_move:
        if not best_move_is_capture:
            bonus = int(allowance) ** 2
            update_history(node.side_to_move(), best_move, bonus)
            if prior_move and prior_move.piece_type != PieceType.NULL:
                update_counter(node.side_to_move() ^ 1, prior_move, best_move)
                # penalize prior move that allowed this good move
                # TODO: make sure that move was a quiet move?
                if len(node.moves) > 1 and node.moves[-1] != PieceType.NULL:
                    update_history(node.side_to_move(), node.moves[-2], -(bonus + 4))
    elif allowance_to_depth(allowance) >= 2.5 and not best_move_is_capture:
        assert(best_val <= a)
        # reward the move that caused this node to fail low
        # TODO: make sure node.moves[-2] was a quiet move?
        # TODO: maybe don't reward at too shallow depth (less confident of it)
        # bonus = (depth * depth) + (2 * depth) - 2
        bonus = int(allowance) ** 2
        if len(node.moves) > 1 and node.moves[-2] != PieceType.NULL:
            update_history(node.side_to_move(), node.moves[-2], bonus)

    if best_val == LOW_BOUND:
        print("best_val is LOW_BOUND, node.moves", node.moves, best_val)
    # assert(best_val > LOW_BOUND)
    
    best_move = best_move or Move(PieceType.NULL)
    if best_val <= a_orig: bound_type = tt.BoundType.HI_BOUND
    elif best_val >= b: bound_type = tt.BoundType.LO_BOUND
    else: bound_type = tt.BoundType.EXACT
    tt.save_tt_entry(tt.TTEntry(pos_key, best_move.compact(),
                                bound_type, best_val, allowance, static_eval))

    if is_root:
        real_pv = a_orig < best_val < b
        print("node_count:", node_count, "avg ply:", ply_count / (ply_iter or 1), "max ply:", ply_max, "val", best_val)
        print("REAL PV:" if real_pv else "pv:", si[ply].pv)
        print()

    return best_val

def qsearch(node, si, ply, alpha, beta, allowance, pv_node, in_check):
    global node_count
    assert(pv_node or alpha == beta-1)
    node_count += 1

    if pv_node:
        si[ply] = SearchInfo()
        si[ply+1] = SearchInfo()

    tt_hit = False
    a_orig = alpha

    tt_hit, tt_ind, tt_entry = tt.get_tt_index(node.zobrist_hash)
    if not pv_node:
        if tt_hit and tt_entry.depth <= allowance:
            if tt_entry.bound_type == tt.BoundType.EXACT:
                return tt_entry.value
            
            if tt_entry.bound_type == tt.BoundType.LO_BOUND and tt_entry.value >= beta:
                alpha = max(alpha, tt_entry.value)
            elif tt_entry.bound_type == tt.BoundType.HI_BOUND and tt_entry.value < alpha:
                beta = min(beta, tt_entry.value)

            if alpha >= beta:
                update_ply_stat(ply)
                return tt_entry.value
    
    # to stop search of endless checks, including repetition checks
    if in_check:
        num_moves = len(node.moves)
        if allowance <= 1 and num_moves > 3 \
           and node.moves[-3].move_type == MoveType.check:
            update_ply_stat(ply)
            return evaluate(node)
    
    static_eval = None
    if tt_hit:
        static_eval = tt_entry.static_eval
    
    best_move = Move(PieceType.NULL)
    if in_check:
        best_value = start_val = LOW_BOUND
    else:
        if static_eval is None:
            best_value = start_val = static_eval = evaluate(node)
        else:
            best_value = start_val = static_eval

        if best_value >= beta:
            # "stand pat"
            if not tt_hit:
                tt.save_tt_entry(tt.TTEntry(node.zobrist_hash,
                                        Move(PieceType.NULL, None, None).compact(),
                                        tt.BoundType.LO_BOUND, best_value, allowance, static_eval))
            update_ply_stat(ply)
            return best_value

        if pv_node and best_value > alpha:
            alpha = best_value

    score = None
    move_count = 0

    legal_moves = node.generate_moves()
    moves = sort_moves(legal_moves, node, si, ply, True)
    # moves = list(node.children(si, ply, quiescence=True))
    for move in moves:
        # if ' '.join(map(str,node.moves)) == "Nc6-d4":
        #     print("debug")

        child = move.position

        move_count += 1
        gives_check = child.in_check()
        
        is_capture = move.to_sq & node.occupied[node.side_to_move() ^ 1]
        
        if not in_check and not gives_check:
            # Futility pruning
            # .. try to avoid calling eval_see
            pt_captured = node.squares[bit_position(move.to_sq)]
            if start_val + MG_PIECES[PieceType.base_type(pt_captured)] + MG_PIECES[PieceType.P] <= alpha:
                continue
            see_score = move.see_score if move.see_score is not None else eval_see(node, move)
            if start_val + see_score + MG_PIECES[PieceType.P] <= alpha \
               and see_score < 0:
                continue

        if not in_check or not is_capture:
            see_score = move.see_score if move.see_score is not None else eval_see(node, move)
            if see_score < 0:
                continue
            
        # print("qsearch", end=" ")
        # print_moves(child.position.moves)
        score = -qsearch(child, si, ply+1, -beta, -alpha, allowance * move.prob, pv_node, gives_check)
        
        if score > best_value:
            best_value = score
            if score > alpha:
                if pv_node and score < beta:
                    alpha = score
                    best_move = move
                    si[ply].pv = [move] + si[ply+1].pv
                    si[ply+1].pv = []
                else:
                    # assert score >= beta
                    if score >= beta:
                        tt.save_tt_entry(tt.TTEntry(node.zobrist_hash, move.compact(),
                                                    tt.BoundType.LO_BOUND, best_value, allowance, static_eval))
                        update_ply_stat(ply)
                        return score
        
    if len(moves) == 0:
        best_value = evaluate(node)
        update_ply_stat(ply)
        assert(not in_check or (best_value == -1000000 or best_value == 0))

    if pv_node and best_value > a_orig: bound_type = tt.BoundType.EXACT
    else: bound_type = tt.BoundType.HI_BOUND
    tt.save_tt_entry(tt.TTEntry(node.zobrist_hash, best_move.compact(),
                                bound_type, best_value, allowance, static_eval))
    return best_value

def find_pv(root_pos):
    moves = []
    pos = Position(root_pos)
    
    def find_next_move():
        found, tt_ind, tt_entry = tt.get_tt_index(pos.zobrist_hash)
        if found:
            move = Move.move_uncompacted(tt_entry.move)
            if move != 0 and tt_entry.bound_type in [tt.BoundType.EXACT, tt.BoundType.LO_BOUND]:
                return True, move
            else:
                return False, move
        return False, 0

    found, move = find_next_move()
    while found and len(moves) < 20:
        moves.append(move)
        pos.make_move(move)
        found, move = find_next_move()
        
    return moves

def sort_moves(moves, position, si, ply, quiescence):
    from_pv = [] 
    captures = []
    killers = []
    counters = []
    other_moves = []
    checks = []

    side = position.side_to_move()
    other = position.occupied[side ^ 1]
    counter = lookup_counter(side ^ 1, position.last_move())

    ep_default_value = (0, 0, 0, 0)
    ep_us_before = next(next_en_prise(position, position.side_to_move()), ep_default_value)
    ep_them_before = next(next_en_prise(position, position.side_to_move() ^ 1), ep_default_value)
    
    def sort_crit(move, en_prise_sort=False):
        entry = lookup_history(side, move)
        see_val = eval_see(position, move)
        if en_prise_sort:
            ep_us_after_gen = next_en_prise(position, side, move)
            pt, *rest = ep_us_before
            pt2, *rest2 = next(ep_us_after_gen, ep_default_value)
            loss = pt - pt2
            see_val += loss

            ep_them_after_gen = next_en_prise(position, side ^ 1, move)
            pto, *rest = ep_them_before
            pto2, *rest = next(ep_them_after_gen, ep_default_value)
            gain = pto2 - pto
            see_val += gain
            
        hist_val = entry.value if entry else 0
        psqt_val = psqt_value_sq(move.piece_type, move.to_sq, position.side_to_move())
        return (see_val, hist_val, psqt_val)
    
    for move in moves:
        if quiescence:
            if is_capture(move.to_sq, other):
                captures.append(move)
            else:
                in_check = position.in_check()
                try_move = move.position
                if in_check and not try_move.in_check(side):
                    # evade check
                    other_moves.append(move)
                elif move.move_type == MoveType.check:
                    # give check
                    checks.append(move)
        else:
            # if move in si[0].pv + si[ply].pv + find_pv(position):
            if move in find_pv(position):
                from_pv.append(move)
            elif is_capture(move.to_sq, other):
                captures.append(move)
            elif move.move_type == MoveType.check:
                checks.append(move)
            elif counter and counter.move == move:
                counters.append(move)
            elif move in killer_moves[ply]:
                killers.append(move)
            else:
                other_moves.append(move)
                
    captures = sorted(captures, key=sort_crit, reverse=True)
    checks = sorted(checks, key=sort_crit, reverse=True)
    captures_see = map(lambda c: (sort_crit(c), c), captures)
    sorted_cap_see = sorted(captures_see, key=itemgetter(0), reverse=True)

    other_moves.sort(key=lambda m: sort_crit(m, en_prise_sort=True), reverse=True)
    
    if quiescence:
        result = list(itertools.chain(map(itemgetter(1), sorted_cap_see),
                                      checks,
                                      other_moves))
    else:
        cap_see_gt0 = []
        cap_see_lt0 = []
        cap_see_eq0 = []
        for cs in sorted_cap_see:
            see, hist, psqt = cs[0]
            if see > 0:
                cap_see_gt0.append(cs[1])
            elif see == 0:
                cap_see_eq0.append(cs[1])
            else:
                cap_see_lt0.append(cs[1])

        # counters = [c.move for c in sorted(counters, key=lambda c: c, reverse=True)]
        
        result = list(itertools.chain(from_pv, cap_see_gt0, cap_see_eq0, checks, counters, killers, other_moves, cap_see_lt0))

    # gaussian formula
    if len(result):
        a = -.126 * math.log(.001 * len(result) * 3 / 4)
    else:
        a = 0
    mu = 0
    sigma_sq = len(result) * 1.5
    
    total_prob = 0
    for ind, move in enumerate(result):
        move.prob = a * math.e**(-(ind+1 - mu)**2 / (2 * sigma_sq))
        total_prob += move.prob
    if len(result) and total_prob < 1:
        result[0].prob += 1 - total_prob
    
    # print([move.prob for move in result])
    return result

def evaluate(position, debug=False):

    if ' '.join(map(str, position.moves)) == "e2-e4":
        debug = True
    
    # Check for mate
    if position.is_mate():
        return -1000000
    
    # TODO: implement stalemate
    
    evaluations = [0, 0]

    counts = piece_counts(position)

    potentials = [all_pawn_attack_potentials(position, Side.WHITE),
                 all_pawn_attack_potentials(position, Side.BLACK)]
    
    for side in [Side.WHITE, Side.BLACK]:

        side_str = "WHITE" if side == Side.WHITE else "BLACK"
        
        # count material
        for base_type in [PieceType.P, PieceType.N, PieceType.B,
                           PieceType.R, PieceType.Q, PieceType.K]:
            piece_type = PieceType.piece(base_type, side)
            
            if base_type is not PieceType.K:
                value = counts[piece_type] * material_eval(counts, base_type, side)
                if debug:
                    print(side_str, "Material", HUMAN_PIECE[piece_type], value)
                evaluations[side] += value
                
            # Positional bonuses and penalties:

            # ..rook considerations
            if base_type == PieceType.R:
                for rook in iterate_pieces(position.pieces[piece_type]):
                    value = rook_position_bonus(rook, position, side)
                    if debug:
                        print(side_str, "Rook Position", HUMAN_PIECE[piece_type], value)
                    evaluations[side] += value
                
            # ..minor outpost, minor behind pawn
            if base_type in [PieceType.B, PieceType.N]:
                for minor in iterate_pieces(position.pieces[piece_type]):
                    value = minor_outpost_bonus(base_type, position, side, potentials)
                    if debug:
                        print(side_str, "Minor Outpost", HUMAN_PIECE[piece_type], value)
                    evaluations[side] += value
                
                value = minor_behind_pawn(piece_type, position, side)
                if debug:
                    print(side_str, "Minor Behind Pawn", HUMAN_PIECE[piece_type], value)
                evaluations[side] += value
            
            # ..pawn structure
            if base_type == PieceType.P:
                value = pawn_structure(position, side)
                if debug:
                    print(side_str, "Pawn Structure", value)
                evaluations[side] += value

                value = pawn_potential_penalty(position, side, potentials)
                if debug:
                    print(side_str, "Pawn Potential Penalty", value)
                evaluations[side] -= value
                
            # ..piece-square table adjustments
            if base_type in [PieceType.P, PieceType.N, PieceType.B, PieceType.K]:
                value = psqt_value(piece_type, position, side)
                if debug:
                    print(side_str, "PSQT adjustments", HUMAN_PIECE[piece_type], value)
                evaluations[side] += value

        # center attacks bonus
        value = center_attacks_bonus(position, side)
        if debug: print(side_str, "Center Attack Bonus", value)
        evaluations[side] += value
                
        # weak/hanging pieces penalties
        for ep in next_en_prise(position, side):
            pt, *rest = ep
            bt = PieceType.base_type(pt)
            value = (MG_PIECES[bt] / MG_PIECES[PieceType.P]) * 30
            if debug:
                print(side_str, "En-prise penalties", HUMAN_PIECE[bt], value)
            evaluations[side] -= value
        
        # pins and discoveries to king
        discoverers, pinned = discoveries_and_pins(position, side)
        # pins and discoveries to queen
        q_discoverers, q_pinned = discoveries_and_pins(position, side, PieceType.Q)
        
        # unprotected
        value = unprotected_penalty(position, side, pinned + q_pinned)
        if debug:
            print(side_str, "Weak/Hanging penalties", value)
        evaluations[side] -= value
        
        value = len(pinned) * 100
        if debug:
            print(side_str, "Pins to King penalty", value)
        evaluations[side] -= value
        
        value = len(discoverers) * 150
        if debug:
            print(side_str, "Discovery threats to King penalty", value)
        evaluations[side] -= value
        
        value = len(q_pinned) * 40
        if debug:
            print(side_str, "Pins to Queen penalty", value)
        evaluations[side] -= value
        
        value = len(q_discoverers) * 60
        if debug:
            print(side_str, "Discovery threats to Queen penalty", value)
        evaluations[side] -= value

        # mobility, taking pins to king into account
        value = mobility(position, side, pinned) * 5
        if debug:
            print(side_str, "Mobility", value)
        evaluations[side] += value
        
        # king safety, castle readiness
        value = 0
        if side == Side.WHITE:
            if preserved_castle_rights(position.position_flags, Side.WHITE):
                value -= 15 # need to somehow reward being castled :\
            if white_can_castle_kingside(position.position_flags, position.attacks[Side.BLACK], position.occupied[Side.WHITE]):
                value += (2 - count_bits(position.occupied[Side.WHITE] & (F1 | G1))) * 8
            elif white_can_castle_queenside(position.position_flags, position.attacks[Side.BLACK], position.occupied[Side.WHITE]):
                value += (3 - count_bits(position.occupied[Side.WHITE] & (D1 | C1 | B1))) * 8
        else:
            if preserved_castle_rights(position.position_flags, Side.BLACK):
                value -= 15
            if black_can_castle_kingside(position.position_flags, position.attacks[Side.WHITE], position.occupied[Side.BLACK] ^ FULL_BOARD):
                value += (2 - count_bits(position.occupied[Side.BLACK] & (F8 | G8))) * 8
            elif black_can_castle_queenside(position.position_flags, position.attacks[Side.WHITE], position.occupied[Side.BLACK] ^ FULL_BOARD):
                value += (3 - count_bits(position.occupied[Side.BLACK] & (D8 | C8 | B8))) * 8
        if debug:
            print(side_str, "King Safety", value)
        evaluations[side] += value

        king_zone_us = king_safety_squares(position, side)
        king_zone_them = king_safety_squares(position, side ^ 1)

        # .. pawn cover of own king
        value = pawn_cover_bonus(king_zone_us, position, side)
        if debug:
            print(side_str, "Pawn Cover", value)
        evaluations[side] += value
        
        # .. king attack bonuses
        # white += king_zone_attack_bonus(king_zone_b, position, Side.WHITE)
        # black += king_zone_attack_bonus(king_zone_w, position, Side.BLACK)

    res_value = int(evaluations[Side.WHITE] - evaluations[Side.BLACK])
    if debug:
        print("EVAL", res_value)
    if position.white_to_move():
        return res_value
    else:
        return -res_value

def print_moves(moves):
    print(' '.join(map(str,moves)))

def perft_outer(depth):
    si = [None] * 64
    return perft(depth, si)

def perft(pos, depth, is_root):
    cnt = nodes = 0
    leaf = depth == 2
    moves = list(pos.generate_moves())
    for move in moves:
        if is_root and depth <= 1:
            cnt = 1
            nodes += 1
        else:
            child = Position(pos)
            child.make_move(move)
            if leaf:
                cnt = len(list(child.generate_moves())) 
            else:
                cnt = perft(child, depth - 1, False)
            nodes += cnt
        if is_root:
            print("move:", str(move), cnt)
    return nodes

def evaluate_moves(position):
    moves = list(position.generate_moves())
    scores = []
    for move in moves:
        pos = Position(position)
        pos.make_move(move)
        scores.append(evaluate(pos))
    res = list(sorted(zip(map(str,moves), scores), key=lambda x: x[1]))
    import pprint
    return pprint.pprint(res)
