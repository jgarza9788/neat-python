import math
import random

from neat.indexer import Indexer
from neat.six_util import iteritems, itervalues

# TODO: Provide some sort of optional cross-species performance criteria, which
# are then used to control stagnation and possibly the mutation rate configuration.
# This scheme should be adaptive so that species do not evolve to become "cautious"
# and only make very slow progress.


class DefaultReproduction(object):
    """
    Handles creation of genomes, either from scratch or by sexual or asexual
    reproduction from parents. Implements the default NEAT-python reproduction
    scheme: explicit fitness sharing with fixed-time species stagnation.
    """
    def __init__(self, config, reporters):
        self.config = config
        params = config.get_type_config(self)
        self.elitism = int(params.get('elitism'))
        self.survival_threshold = float(params.get('survival_threshold'))

        self.reporters = reporters
        self.genome_indexer = Indexer(1)
        self.stagnation = config.stagnation_type(config, reporters)
        self.ancestors = {}

    def create_new(self, num_genomes):
        new_genomes = {}
        for i in range(num_genomes):
            key = self.genome_indexer.get_next()
            g = self.config.genotype.create(self.config, key)
            new_genomes[key] = g
            self.ancestors[key] = tuple()

        return new_genomes

    def reproduce(self, species, pop_size):
        # TODO: I don't like this modification of the species object,
        # because it requires internal knowledge of the object.

        # Filter out stagnated species and collect the set of non-stagnated species members.
        num_remaining = 0
        species_fitness = []
        avg_adjusted_fitness = 0.0
        for sid, s, stagnant in self.stagnation.update(species.species):
            if stagnant:
                self.reporters.species_stagnant(s)
            else:
                num_remaining += 1

                # Compute adjusted fitness.
                species_sum = 0.0
                for m in itervalues(s.members):
                    af = m.fitness / len(s.members)
                    species_sum += af

                sfitness = species_sum / len(s.members)
                species_fitness.append((sid, s, sfitness))
                avg_adjusted_fitness += sfitness

        # No species left.
        if 0 == num_remaining:
            species.species = {}
            return []

        avg_adjusted_fitness /= len(species_fitness)
        self.reporters.info("Average adjusted fitness: {:.3f}".format(avg_adjusted_fitness))

        # Compute the number of new individuals to create for the new generation.
        spawn_amounts = []
        for sid, s, sfitness in species_fitness:
            spawn = len(s.members)
            if sfitness > avg_adjusted_fitness:
                spawn *= 1.1
            else:
                spawn *= 0.9
            spawn_amounts.append(spawn)

        # Normalize the spawn amounts so that the next generation is roughly
        # the population size requested by the user.
        total_spawn = sum(spawn_amounts)
        norm = pop_size / total_spawn
        spawn_amounts = [int(round(n * norm)) for n in spawn_amounts]
        self.reporters.info("Spawn amounts: {0}".format(spawn_amounts))
        self.reporters.info('Species fitness  : {0!r}'.format([sfitness for sid, s, sfitness in species_fitness]))

        new_population = {}
        species.species = {}
        for spawn, (sid, s, sfitness) in zip(spawn_amounts, species_fitness):
            # If elitism is enabled, each species always at least gets to retain its elites.
            spawn = max(spawn, self.elitism)

            if spawn <= 0:
                continue

            # The species has at least one member for the next generation, so retain it.
            old_members = list(iteritems(s.members))
            s.members = {}
            species.species[sid] = s

            # Sort members in order of descending fitness.
            old_members.sort(reverse=True, key=lambda x: x[1].fitness)

            # Transfer elites to new generation.
            if self.elitism > 0:
                for i, m in old_members[:self.elitism]:
                    new_population[i] = m
                    spawn -= 1

            if spawn <= 0:
                continue

            # Only use the survival threshold fraction to use as parents for the next generation.
            repro_cutoff = int(math.ceil(self.survival_threshold * len(old_members)))
            # Use at least two parents no matter what the threshold fraction result is.
            repro_cutoff = max(repro_cutoff, 2)
            old_members = old_members[:repro_cutoff]

            # Randomly choose parents and produce the number of offspring allotted to the species.
            while spawn > 0:
                spawn -= 1

                parent1_id, parent1 = random.choice(old_members)
                parent2_id, parent2 = random.choice(old_members)

                # Note that if the parents are not distinct, crossover will produce a
                # genetically identical clone of the parent (but with a different ID).
                gid = self.genome_indexer.get_next()
                child = parent1.crossover(parent2, gid)
                child.mutate(self.config)
                new_population[gid] = child
                self.ancestors[gid] = (parent1_id, parent2_id)


        # Sort species by ID (purely for ease of reading the reported list).
        # TODO: This should probably be done by the species object.
        #species.species.sort(key=lambda sp: sp.ID)

        return new_population